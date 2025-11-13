from django.utils.decorators import method_decorator
from django.views.generic import TemplateView, ListView, DetailView, UpdateView
from django.shortcuts import get_object_or_404
from django.core.exceptions import PermissionDenied
from django.contrib.auth.views import redirect_to_login

from accounting.models import Customer, Invoice, Payment
from accounting.forms import CustomerProfileForm
from django.db.models import Sum


class CustomerPortalMixin:
    """
    Mixin لكل فيوز في بوابة الزبون:
    - يتأكد أن المستخدم مسجّل دخول
    - يجلب Customer المرتبط به
    - يخزنه في self.customer
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        try:
            self.customer = Customer.objects.select_related("user").get(user=request.user)
        except Customer.DoesNotExist:
            # المستخدم مسجّل دخول لكن ليس لديه Customer مرتبط
            raise PermissionDenied("لا يوجد حساب زبون مرتبط بهذا المستخدم.")

        return super().dispatch(request, *args, **kwargs)


class PortalDashboardView(CustomerPortalMixin, TemplateView):
    template_name = "portal/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        customer = self.customer

        invoices = (
            Invoice.objects
            .filter(customer=customer)
            .order_by("-issued_at", "-id")
        )
        payments = (
            Payment.objects
            .filter(customer=customer)
            .order_by("-date", "-id")
        )

        total_invoices = invoices.aggregate(s=Sum("total_amount"))["s"] or 0
        total_paid = payments.aggregate(s=Sum("amount"))["s"] or 0

        ctx["customer"] = customer
        ctx["invoice_count"] = invoices.count()
        ctx["payment_count"] = payments.count()
        ctx["total_invoices"] = total_invoices
        ctx["total_paid"] = total_paid
        ctx["balance"] = total_invoices - total_paid
        ctx["recent_invoices"] = invoices[:5]
        ctx["recent_payments"] = payments[:5]
        return ctx


class PortalInvoiceListView(CustomerPortalMixin, ListView):
    model = Invoice
    template_name = "portal/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 20

    def get_queryset(self):
        return (
            Invoice.objects
            .filter(customer=self.customer)
            .order_by("-issued_at", "-id")
        )


class PortalInvoiceDetailView(CustomerPortalMixin, DetailView):
    model = Invoice
    template_name = "portal/invoice_detail.html"
    context_object_name = "invoice"
    slug_field = "number"
    slug_url_kwarg = "number"

    def get_object(self, queryset=None):
        # تأكد أن الفاتورة تخص هذا الزبون فقط
        return get_object_or_404(
            Invoice.objects.filter(customer=self.customer),
            number=self.kwargs.get("number"),
        )


class PortalPaymentListView(CustomerPortalMixin, ListView):
    model = Payment
    template_name = "portal/payment_list.html"
    context_object_name = "payments"
    paginate_by = 20

    def get_queryset(self):
        return (
            Payment.objects
            .filter(customer=self.customer)
            .select_related("invoice")
            .order_by("-date", "-id")
        )


class PortalProfileUpdateView(CustomerPortalMixin, UpdateView):
    """
    يسمح للزبون بتحديث بياناته (Customer المرتبط به).
    """
    model = Customer
    form_class = CustomerProfileForm
    template_name = "portal/profile_form.html"
    context_object_name = "customer"

    def get_object(self, queryset=None):
        return self.customer

    def get_success_url(self):
        from django.urls import reverse
        return reverse("portal:dashboard")


class PortalInvoicePrintView(CustomerPortalMixin, DetailView):
    """
    صفحة طباعة الفاتورة من بوابة الزبون.
    تستخدم نفس قالب الطباعة في المحاسبة.
    """
    model = Invoice
    template_name = "accounting/invoice_print.html"
    context_object_name = "invoice"
    slug_field = "number"
    slug_url_kwarg = "number"

    def get_object(self, queryset=None):
        # نفس منطق PortalInvoiceDetailView: لا نسمح إلا بفواتيره هو
        return get_object_or_404(
            Invoice.objects.filter(customer=self.customer),
            number=self.kwargs.get("number"),
        )
