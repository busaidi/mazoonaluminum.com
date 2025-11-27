# contacts/views.py
from decimal import Decimal

from django.db.models import Sum
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
)

from accounting.models import Payment
from .forms import ContactForm, ContactAddressFormSet
from .models import Contact
from .services import save_contact_with_addresses


# ============================================================
# Base mixin for contacts staff
# ============================================================

class ContactsStaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    مكسين بسيط لتقييد الوصول لموظفي النظام.
    لاحقاً ممكن تستبدله بمكسين مشترك من core.
    """

    raise_exception = True  # 403 بدال ريديركت لا نهائي

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.is_staff

    @property
    def section(self) -> str:
        """
        تستخدمها القوالب لتحديد تبويب جهات الاتصال.
        """
        return "contacts"


# ============================================================
# List & Detail views
# ============================================================

class ContactListView(ContactsStaffRequiredMixin, ListView):
    model = Contact
    template_name = "contacts/list.html"
    context_object_name = "contacts"
    paginate_by = 25

    def get_queryset(self):
        # نستخدم select_related لتقليل عدد الكويريز (user + company)
        qs = (
            Contact.objects
            .all()
            .select_related("user", "company")
            .order_by("name", "id")
        )

        # فلتر بسيط للنشاط
        status = self.request.GET.get("status", "active").strip()
        if status == "active":
            qs = qs.active()
        elif status == "inactive":
            qs = qs.inactive()
        # لو "all" أو غيره: لا نفلتر، نرجع الكل

        # فلتر الدور: customer / supplier / owner / employee
        role = self.request.GET.get("role", "").strip().lower()
        if role == "customer":
            qs = qs.customers()
        elif role == "supplier":
            qs = qs.suppliers()
        elif role == "owner":
            qs = qs.owners()
        elif role == "employee":
            qs = qs.employees()

        # فلتر نوع الكيان: person / company
        kind = self.request.GET.get("kind", "").strip().lower()
        if kind == "person":
            qs = qs.persons()
        elif kind == "company":
            qs = qs.companies()

        # 🔹 فلتر الشركة (اختياري): ?company=<id>
        company_id = self.request.GET.get("company", "").strip()
        if company_id:
            qs = qs.filter(company_id=company_id)

        # بحث نصي
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(company_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(email__icontains=q)
            )

        # نخزن القيم عشان نرجعها في الكونتكست
        self.search_query = q
        self.role_filter = role
        self.kind_filter = kind
        self.status_filter = status
        self.company_filter = company_id

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = getattr(self, "search_query", "")
        ctx["role"] = getattr(self, "role_filter", "")
        ctx["kind"] = getattr(self, "kind_filter", "")
        ctx["status"] = getattr(self, "status_filter", "active")
        ctx["company_id"] = getattr(self, "company_filter", "")

        # السياق القديم
        ctx["section"] = self.section
        ctx["subsection"] = "contacts"

        # 🔹 هذا عشان accounting/_nav.html
        ctx["accounting_section"] = "customers"

        return ctx


class ContactDetailView(ContactsStaffRequiredMixin, DetailView):
    model = Contact
    template_name = "contacts/detail.html"
    context_object_name = "contact"

    def get_queryset(self):
        """
        نستخدم select_related لجلب الشركة المرتبطة من نفس الكويري،
        عشان نقلل عدد الاستعلامات عند استخدام contact.company في القالب.
        """
        return Contact.objects.select_related("company")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        contact = self.object

        # -----------------------------
        # العناوين
        # -----------------------------
        addresses = contact.addresses.all().order_by(
            "-is_primary",
            "address_type",
            "id",
        )
        ctx["addresses"] = addresses

        # -----------------------------
        # ملخص مالي
        # -----------------------------
        ctx["total_invoiced"] = contact.total_invoiced
        ctx["total_paid"] = contact.total_paid
        ctx["balance"] = contact.balance

        # -----------------------------
        # الدفعات المرتبطة بهذا الكونتاكت
        # -----------------------------
        payments_qs = (
            Payment.objects
            .filter(contact=contact)
            .select_related("method")
            .order_by("-date", "-id")
        )

        total_in = (
            payments_qs.filter(direction=Payment.Direction.IN)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.000")
        )
        total_out = (
            payments_qs.filter(direction=Payment.Direction.OUT)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.000")
        )

        ctx["payments"] = payments_qs
        ctx["payments_total_in"] = total_in
        ctx["payments_total_out"] = total_out

        # سياق الأقسام
        ctx["section"] = self.section
        ctx["subsection"] = "contacts"

        # 🔹 عشان ناف المحاسبة
        ctx["accounting_section"] = "customers"

        return ctx


# ============================================================
# Create / Update / Delete views (بدون BaseFormView)
# ============================================================

class ContactCreateView(ContactsStaffRequiredMixin, CreateView):
    """
    إنشاء جهة اتصال جديدة مع عناوينها.
    """
    model = Contact
    form_class = ContactForm
    template_name = "contacts/form.html"

    def get_success_url(self):
        return reverse("contacts:contact_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # في الإنشاء ما عندنا object بعد، فـ instance = None
        instance = getattr(self, "object", None)

        if self.request.method == "POST":
            ctx["address_formset"] = ContactAddressFormSet(
                self.request.POST,
                instance=instance,
            )
        else:
            ctx["address_formset"] = ContactAddressFormSet(
                instance=instance,
            )

        ctx["section"] = self.section
        ctx["subsection"] = "contacts"
        # 🔹 عشان ناف المحاسبة
        ctx["accounting_section"] = "customers"
        return ctx

    def form_valid(self, form):
        ctx = self.get_context_data(form=form)
        address_formset = ctx.get("address_formset")

        if address_formset is None or not address_formset.is_valid():
            # لو في أخطاء في العناوين نرجّع نفس الفورم مع الأخطاء
            return self.render_to_response(ctx)

        # نحفظ جهة الاتصال + العناوين في معاملة واحدة
        self.object = save_contact_with_addresses(form, address_formset)
        messages.success(self.request, _("تم حفظ جهة الاتصال بنجاح."))
        return redirect(self.get_success_url())


class ContactUpdateView(ContactsStaffRequiredMixin, UpdateView):
    """
    تعديل جهة اتصال وعناوينها.
    """
    model = Contact
    form_class = ContactForm
    template_name = "contacts/form.html"

    def get_success_url(self):
        return reverse("contacts:contact_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # في التعديل self.object = جهة الاتصال الحالية
        instance = getattr(self, "object", None)

        if self.request.method == "POST":
            ctx["address_formset"] = ContactAddressFormSet(
                self.request.POST,
                instance=instance,
            )
        else:
            ctx["address_formset"] = ContactAddressFormSet(
                instance=instance,
            )

        ctx["section"] = self.section
        ctx["subsection"] = "contacts"
        # 🔹 عشان ناف المحاسبة
        ctx["accounting_section"] = "customers"
        return ctx

    def form_valid(self, form):
        # في UpdateView، self.object تم تعيينه في post() قبل form_valid()
        ctx = self.get_context_data(form=form)
        address_formset = ctx.get("address_formset")

        if address_formset is None or not address_formset.is_valid():
            return self.render_to_response(ctx)

        # نحفظ التعديلات على جهة الاتصال والعناوين
        self.object = save_contact_with_addresses(form, address_formset)
        messages.success(self.request, _("تم حفظ جهة الاتصال بنجاح."))
        return redirect(self.get_success_url())


class ContactDeleteView(ContactsStaffRequiredMixin, DeleteView):
    model = Contact
    template_name = "contacts/confirm_delete.html"
    success_url = reverse_lazy("contacts:contact_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["section"] = self.section
        ctx["subsection"] = "contacts"
        # 🔹 لو حاب تحذف من داخل سياق المحاسبة برضه يظل التبويب نشط
        ctx["accounting_section"] = "customers"
        return ctx

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        name = str(self.object)
        response = super().delete(request, *args, **kwargs)
        messages.success(request, _("تم حذف جهة الاتصال: %(name)s") % {"name": name})
        return response


# ============================================================
# Autocomplete view (JSON)
# ============================================================

class ContactAutocompleteView(ContactsStaffRequiredMixin, View):
    """
    إرجاع قائمة مبسطة من جهات الاتصال بصيغة JSON.
    مفيدة للـ select2 / auto-complete في التطبيقات الأخرى.
    """

    def get(self, request, *args, **kwargs):
        q = request.GET.get("q", "").strip()

        qs = (
            Contact.objects
            .active()
            .select_related("company")
            .order_by("name", "id")
        )

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(company_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(email__icontains=q)
            )

        qs = qs[:20]

        results = []
        for c in qs:
            results.append(
                {
                    "id": c.pk,
                    "text": c.name,
                    "kind": c.kind,
                    "company_id": c.company_id,
                    "company_name": c.company.name if c.company else "",
                    "is_customer": c.is_customer,
                    "is_supplier": c.is_supplier,
                    "is_owner": c.is_owner,
                    "is_employee": c.is_employee,
                }
            )

        return JsonResponse({"results": results})
