# accounting/views.py

from django.contrib.auth.decorators import user_passes_test
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    FormView,
    TemplateView, UpdateView, DeleteView,
)

from .forms import InvoiceForm, PaymentForInvoiceForm, CustomerForm
from .models import Invoice, Payment, Customer


def is_accounting_staff(user):
    """
    الموظف المصرح له بالمحاسبة:
    - مستخدم مفعل
    - عضو في المجموعة 'accounting_staff'
    """
    return (
        user.is_authenticated
        and user.is_active
        and user.groups.filter(name="accounting_staff").exists()
    )


accounting_staff_required = user_passes_test(is_accounting_staff)


@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceListView(ListView):
    model = Invoice
    template_name = "accounting/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related("customer")
        )
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_filter"] = self.request.GET.get("status", "")
        return ctx


@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceCreateView(CreateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = "accounting/invoice_form.html"

    def get_initial(self):
        initial = super().get_initial()
        customer_id = self.request.GET.get("customer")

        if customer_id:
            # تعبئة فورم الفاتورة بالزبون تلقائيًا
            initial["customer"] = customer_id

        return initial

    def get_success_url(self):
        from django.urls import reverse
        return reverse("accounting:invoice_list")


@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceDetailView(DetailView):
    model = Invoice
    template_name = "accounting/invoice_detail.html"
    context_object_name = "invoice"
    slug_field = "number"
    slug_url_kwarg = "number"


@method_decorator(accounting_staff_required, name="dispatch")
class InvoicePaymentCreateView(FormView):
    """
    إنشاء دفعة جديدة لفتورة معينة.
    URL: /accounting/invoices/<number>/payments/new/
    """
    template_name = "accounting/invoice_payment_form.html"
    form_class = PaymentForInvoiceForm

    def dispatch(self, request, *args, **kwargs):
        # نجيب الفاتورة من رقمها مرة واحدة ونخزنها على self
        self.invoice = get_object_or_404(
            Invoice.objects.select_related("customer"),
            number=kwargs.get("number"),
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["invoice"] = self.invoice
        return ctx

    def get_initial(self):
        initial = super().get_initial()
        from django.utils import timezone
        initial.setdefault("date", timezone.now().date())
        return initial

    def form_valid(self, form):
        # ننشئ الـ Payment ونربطه بنفس العميل والفاتورة
        payment = form.save(commit=False)
        payment.customer = self.invoice.customer
        payment.invoice = self.invoice
        payment.save()  # هذا تلقائيًا يحدث paid_amount في save()

        # نرجع إلى صفحة تفاصيل الفاتورة
        return super().form_valid(form)

    def get_success_url(self):
        from django.urls import reverse
        return reverse(
            "accounting:invoice_detail",
            kwargs={"number": self.invoice.number},
        )



@method_decorator(accounting_staff_required, name="dispatch")
class AccountingDashboardView(TemplateView):
    """
    لوحة مبسطة للمحاسبة:
    - إحصائيات عامة
    - آخر الفواتير
    - آخر الدفعات
    """
    template_name = "accounting/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        invoices = Invoice.objects.select_related("customer")
        payments = Payment.objects.select_related("customer", "invoice")

        total_amount = invoices.aggregate(s=Sum("total_amount"))["s"] or 0
        total_paid = invoices.aggregate(s=Sum("paid_amount"))["s"] or 0

        ctx["invoice_count"] = invoices.count()
        ctx["customer_count"] = Customer.objects.count()
        ctx["payment_count"] = payments.count()
        ctx["total_amount"] = total_amount
        ctx["total_paid"] = total_paid
        ctx["total_balance"] = total_amount - total_paid

        ctx["recent_invoices"] = invoices.order_by("-issued_at", "-id")[:5]
        ctx["recent_payments"] = payments.order_by("-date", "-id")[:5]

        return ctx


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerListView(ListView):
    model = Customer
    template_name = "accounting/customer_list.html"
    context_object_name = "customers"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(company_name__icontains=q)
        return qs


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerCreateView(CreateView):
    model = Customer
    form_class = CustomerForm
    template_name = "accounting/customer_form.html"

    def get_success_url(self):
        from django.urls import reverse
        return reverse("accounting:customer_list")


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerUpdateView(UpdateView):
    model = Customer
    form_class = CustomerForm
    template_name = "accounting/customer_form.html"

    def get_success_url(self):
        from django.urls import reverse
        return reverse("accounting:customer_list")


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerDeleteView(DeleteView):
    model = Customer
    template_name = "accounting/customer_confirm_delete.html"

    def get_success_url(self):
        from django.urls import reverse
        return reverse("accounting:customer_list")



@method_decorator(accounting_staff_required, name="dispatch")
class CustomerDetailView(DetailView):
    model = Customer
    template_name = "accounting/customer_detail.html"
    context_object_name = "customer"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        customer = self.object

        invoices = (
            customer.invoices.all()
            .order_by("-issued_at", "-id")
        )
        payments = (
            customer.payments.all()
            .select_related("invoice")
            .order_by("-date", "-id")
        )

        from django.db.models import Sum

        total_invoices = invoices.aggregate(s=Sum("total_amount"))["s"] or 0
        total_paid = payments.aggregate(s=Sum("amount"))["s"] or 0

        ctx["invoices"] = invoices
        ctx["payments"] = payments
        ctx["total_invoices"] = total_invoices
        ctx["total_paid"] = total_paid
        ctx["balance"] = total_invoices - total_paid

        return ctx


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerPaymentCreateView(FormView):
    """
    إنشاء دفعة مرتبطة بزبون فقط (بدون فاتورة محددة).
    URL: /accounting/customers/<pk>/payments/new/
    """
    template_name = "accounting/customer_payment_form.html"
    form_class = PaymentForInvoiceForm

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(Customer, pk=kwargs.get("pk"))
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        from django.utils import timezone
        initial.setdefault("date", timezone.now().date())
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["customer"] = self.customer
        return ctx

    def form_valid(self, form):
        payment = form.save(commit=False)
        payment.customer = self.customer
        payment.invoice = None  # دفعة عامة، ليست لفاتورة معينة
        payment.save()
        return super().form_valid(form)

    def get_success_url(self):
        from django.urls import reverse
        return reverse("accounting:customer_detail", kwargs={"pk": self.customer.pk})




