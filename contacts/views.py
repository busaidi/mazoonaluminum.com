# contacts/views.py
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
        تستخدمها القوالب لتحديد تبويب الكونتاكت.
        """
        return "contacts"


# ============================================================
# List & Detail views
# ============================================================

class ContactListView(ContactsStaffRequiredMixin, ListView):
    model = Contact
    template_name = "contacts/list.html"  # ← مطابق لاسم القالب
    context_object_name = "contacts"
    paginate_by = 25

    def get_queryset(self):
        qs = Contact.objects.all().order_by("name", "id")

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

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = getattr(self, "search_query", "")
        ctx["role"] = getattr(self, "role_filter", "")
        ctx["kind"] = getattr(self, "kind_filter", "")
        ctx["status"] = getattr(self, "status_filter", "active")
        ctx["section"] = self.section
        ctx["subsection"] = "contacts"
        return ctx


class ContactDetailView(ContactsStaffRequiredMixin, DetailView):
    model = Contact
    template_name = "contacts/detail.html"  # ← مطابق لاسم القالب
    context_object_name = "contact"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        contact = self.object

        # العناوين (تُعرض كبطاقات في القالب)
        addresses = contact.addresses.all().order_by(
            "-is_primary",
            "address_type",
            "id",
        )
        ctx["addresses"] = addresses
        ctx["section"] = self.section
        ctx["subsection"] = "contacts"

        # ملخص مالي بسيط (لو فيه فواتير/مدفوعات مربوطة من تطبيق آخر)
        ctx["total_invoiced"] = contact.total_invoiced
        ctx["total_paid"] = contact.total_paid
        ctx["balance"] = contact.balance

        return ctx


# ============================================================
# Create / Update / Delete views
# ============================================================

class ContactBaseFormView(ContactsStaffRequiredMixin):
    """
    مزيج مشترك بين create/update:
    - يستخدم ContactForm
    - يدير ContactAddressFormSet للعناوين.
    """

    model = Contact
    form_class = ContactForm
    template_name = "contacts/form.html"

    def get_success_url(self):
        return reverse("contacts:contact_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
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
        return ctx

    def form_valid(self, form):
        ctx = self.get_context_data(form=form)
        address_formset = ctx.get("address_formset")

        # لو الفورمست غير صالح نرجع القالب مع الأخطاء
        if address_formset is None or not address_formset.is_valid():
            return self.render_to_response(ctx)

        # نستخدم السيرفس لحفظ الكونتاكت + العناوين في transaction
        self.object = save_contact_with_addresses(form, address_formset)
        messages.success(self.request, _("تم حفظ الكونتاكت بنجاح."))
        return redirect(self.get_success_url())


class ContactCreateView(ContactBaseFormView, CreateView):
    """
    إنشاء كونتاكت جديد مع عناوينه.
    """
    pass


class ContactUpdateView(ContactBaseFormView, UpdateView):
    """
    تعديل كونتاكت وعناوينه.
    """
    pass


class ContactDeleteView(ContactsStaffRequiredMixin, DeleteView):
    model = Contact
    template_name = "contacts/confirm_delete.html"  # ← مطابق لاسم القالب
    success_url = reverse_lazy("contacts:contact_list")

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        name = str(self.object)
        response = super().delete(request, *args, **kwargs)
        messages.success(request, _("تم حذف الكونتاكت: %(name)s") % {"name": name})
        return response


# ============================================================
# Autocomplete view (JSON)
# ============================================================

class ContactAutocompleteView(ContactsStaffRequiredMixin, View):
    """
    إرجاع قائمة مبسطة من الكونتاكت بصيغة JSON.
    مفيدة للـ select2 / auto-complete في التطبيقات الأخرى.
    """

    def get(self, request, *args, **kwargs):
        q = request.GET.get("q", "").strip()

        qs = Contact.objects.active().order_by("name", "id")

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
                    "is_customer": c.is_customer,
                    "is_supplier": c.is_supplier,
                    "is_owner": c.is_owner,
                    "is_employee": c.is_employee,
                }
            )

        return JsonResponse({"results": results})
