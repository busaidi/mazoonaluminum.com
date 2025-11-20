# accounting/views.py
import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import (
    login_required,
    permission_required,
    user_passes_test,
)
from django.db import transaction
from django.db.models import Sum, Q, ProtectedError, F
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    FormView,
    TemplateView,
    UpdateView,
    DeleteView,
)

from core.models import AuditLog
from core.services.audit import log_event
from core.services.notifications import create_notification
from core.views.attachments import  AttachmentPanelMixin
from website.models import Product
from .forms import (
    InvoiceForm,
    PaymentForInvoiceForm,
    CustomerForm,
    InvoiceItemFormSet,
    ApplyPaymentForm,
    OrderItemFormSet,
    OrderForm,
    PaymentForm,
    SettingsForm,
)
from .models import Invoice, Payment, Customer, Order, InvoiceItem, Settings
from .services import convert_order_to_invoice, allocate_general_payment

# ============================================================
# Helpers / Permissions
# ============================================================

def is_accounting_staff(user):
    """
    Simple permission check for accounting staff:
    - Authenticated, active user
    - Member of 'accounting_staff' group
    """
    return (
        user.is_authenticated
        and user.is_active
        and user.groups.filter(name="accounting_staff").exists()
    )


accounting_staff_required = user_passes_test(is_accounting_staff)


# ============================================================
# Mixins
# ============================================================

class AccountingSectionMixin:
    """
    Injects 'accounting_section' into context so templates can
    highlight the current section in the accounting navigation.
    """
    section = None  # override in subclasses: 'dashboard', 'invoices', 'customer', 'orders', 'payments'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["accounting_section"] = self.section
        return ctx


class TodayInitialDateMixin:
    """
    Adds today's date as default 'date' initial value if not provided.
    Used for payment forms, etc.
    """
    def get_initial(self):
        initial = super().get_initial()
        initial.setdefault("date", timezone.now().date())
        return initial


class ProductJsonMixin:
    """
    Provides products_json (id → description, price) for JS autocomplete.
    Used in invoice and order forms.
    """
    def get_products_json(self):
        products = Product.objects.filter(is_active=True)
        data = {
            str(p.id): {
                "description": p.description or "",
                "price": str(p.price),
            }
            for p in products
        }
        return mark_safe(json.dumps(data))

    def inject_products_json(self, ctx):
        ctx["products_json"] = self.get_products_json()
        return ctx


# ============================================================
# Invoices
# ============================================================

@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceListView(AccountingSectionMixin, ListView):
    """
    Staff list of invoices with optional status filter.
    """
    section = "invoices"
    model = Invoice
    template_name = "accounting/invoices/list.html"
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


class InvoiceCreateView(AccountingSectionMixin, ProductJsonMixin, CreateView):
    """
    إنشاء فاتورة جديدة مع فورمست للبنود (Invoice Items).
    منطق إنشاء التنبيهات يتم عبر signals على موديل Invoice،
    وليس من داخل هذا الفيو.
    """

    section = "invoices"
    model = Invoice
    form_class = InvoiceForm
    template_name = "accounting/invoices/form.html"

    def get_initial(self):
        initial = super().get_initial()

        # Pre-fill customer if passed in query params
        customer_id = self.request.GET.get("customer")
        if customer_id:
            initial["customer"] = customer_id

        # Pre-fill default terms from Settings (إن وُجدت)
        if not initial.get("terms"):
            from .models import Settings  # لو مش مستوردة فوق
            settings = Settings.get_solo()
            if settings.default_terms:
                initial["terms"] = settings.default_terms

        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # Invoice items formset
        if self.request.POST:
            ctx["item_formset"] = InvoiceItemFormSet(self.request.POST)
        else:
            ctx["item_formset"] = InvoiceItemFormSet()

        # Products JSON for JS auto-fill
        ctx = self.inject_products_json(ctx)

        return ctx

    def form_valid(self, form):
        """
        نحفظ الفاتورة والبنود داخل transaction واحدة:
        - إذا فشل حفظ البنود أو حساب الإجمالي → يتم التراجع عن كل شيء.
        - أوّل save للفاتورة يطلق post_save(created=True) → السيجنال يشتغل.
        """
        context = self.get_context_data()
        item_formset = context["item_formset"]

        # Validate formset first
        if not item_formset.is_valid():
            return self.form_invalid(form)

        with transaction.atomic():
            # 1) Save invoice without total
            invoice = form.save(commit=False)
            invoice.total_amount = Decimal("0")
            invoice.save()  # serial, due_date, terms معالجة في model.save()
            self.object = invoice

            # 2) Save items
            item_formset.instance = invoice
            item_formset.save()

            # 3) Compute total from items
            total = sum(
                (item.subtotal for item in invoice.items.all()),
                Decimal("0"),
            )
            invoice.total_amount = total
            invoice.save(update_fields=["total_amount"])

        # 4) Redirect
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("accounting:invoice_list")


@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceUpdateView(AccountingSectionMixin, ProductJsonMixin, UpdateView):
    """
    Update existing invoice + related items.
    """
    section = "invoices"
    model = Invoice
    form_class = InvoiceForm
    template_name = "accounting/invoices/form.html"
    slug_field = "serial"
    slug_url_kwarg = "serial"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        invoice = self.object

        # Bind formset to existing invoice
        if self.request.POST:
            ctx["item_formset"] = InvoiceItemFormSet(self.request.POST, instance=invoice)
        else:
            ctx["item_formset"] = InvoiceItemFormSet(instance=invoice)

        # Same products JSON used in create
        ctx = self.inject_products_json(ctx)

        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        item_formset = context["item_formset"]

        if not item_formset.is_valid():
            return self.form_invalid(form)

        # Update invoice itself
        invoice = form.save(commit=False)
        invoice.total_amount = Decimal("0")
        invoice.save()
        self.object = invoice

        # Save items changes
        item_formset.instance = invoice
        item_formset.save()

        # Recompute total
        total = sum((item.subtotal for item in invoice.items.all()), Decimal("0"))
        invoice.total_amount = total
        invoice.save(update_fields=["total_amount"])

        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("accounting:invoice_detail", kwargs={"serial": self.object.serial})


@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceDetailView(AttachmentPanelMixin, AccountingSectionMixin, DetailView):
    section = "invoices"
    model = Invoice
    template_name = "accounting/invoices/detail.html"
    context_object_name = "invoice"
    slug_field = "serial"
    slug_url_kwarg = "serial"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx = self.inject_attachment_panel_context(ctx)
        return ctx




@method_decorator(accounting_staff_required, name="dispatch")
class InvoicePaymentCreateView(AccountingSectionMixin, TodayInitialDateMixin, FormView):
    """
    Create a payment for a specific invoice.
    URL: /accounting/invoices/<number>/payments/new/
    """
    section = "payments"
    template_name = "accounting/invoices/payment.html"
    form_class = PaymentForInvoiceForm

    def dispatch(self, request, *args, **kwargs):
        # Load invoice once and store on self
        self.invoice = get_object_or_404(
            Invoice.objects.select_related("customer"),
            serial=kwargs.get("serial"),
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["invoice"] = self.invoice
        return ctx

    # get_initial comes from TodayInitialDateMixin

    def form_valid(self, form):
        # Create payment bound to same customer & invoice
        payment = form.save(commit=False)
        payment.customer = self.invoice.customer
        payment.invoice = self.invoice
        payment.save()  # triggers invoice paid_amount update
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(
            "accounting:invoice_detail",
            kwargs={"serial": self.invoice.serial},
        )


@method_decorator(accounting_staff_required, name="dispatch")
class InvoicePrintView(AccountingSectionMixin, DetailView):
    """
    Print page for invoice (staff side).
    """
    section = "invoices"
    model = Invoice
    template_name = "accounting/invoices/print.html"
    context_object_name = "invoice"
    slug_field = "serial"
    slug_url_kwarg = "serial"


# ============================================================
# Dashboard
# ============================================================

@method_decorator(accounting_staff_required, name="dispatch")
class AccountingDashboardView(AccountingSectionMixin, TemplateView):
    """
    Main accounting dashboard:
    - Counters
    - Recent invoices, payments, orders
    - Pending orders (no invoice)
    - Unpaid invoices
    """
    section = "dashboard"
    template_name = "accounting/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        invoices = Invoice.objects.select_related("customer").all()
        customers = Customer.objects.all()
        payments = Payment.objects.select_related("customer", "invoice").all()
        orders = Order.objects.select_related("customer").all()

        total_amount = invoices.aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        total_paid = invoices.aggregate(s=Sum("paid_amount"))["s"] or Decimal("0")
        total_balance = total_amount - total_paid

        ctx["invoice_count"] = invoices.count()
        ctx["customer_count"] = customers.count()
        ctx["payment_count"] = payments.count()
        ctx["order_count"] = orders.count()

        ctx["total_amount"] = total_amount
        ctx["total_balance"] = total_balance

        ctx["recent_invoices"] = invoices.order_by("-issued_at", "-id")[:5]
        ctx["recent_payments"] = payments.order_by("-date", "-id")[:5]
        ctx["recent_orders"] = orders.order_by("-created_at", "-id")[:5]

        # Orders that are not converted to invoices yet
        ctx["pending_orders"] = (
            orders
            .filter(invoice__isnull=True)
            .order_by("-created_at", "-id")[:5]
        )

        # Unpaid invoices (not fully paid or cancelled)
        ctx["unpaid_invoices"] = (
            invoices
            .exclude(status=Invoice.Status.PAID)
            .exclude(status=Invoice.Status.CANCELLED)
            .filter(total_amount__gt=F("paid_amount"))
            .order_by("-issued_at", "-id")[:5]
        )

        return ctx


# ============================================================
# Customers
# ============================================================

@method_decorator(accounting_staff_required, name="dispatch")
class CustomerListView(AccountingSectionMixin, ListView):
    """
    Staff list of customers, with simple search by name/company.
    """
    section = "customers"  # عشان الناف بار
    model = Customer
    template_name = "accounting/customer/list.html"
    context_object_name = "customers"  # يتطابق مع القالب
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(company_name__icontains=q)
            )
        return qs

@method_decorator(accounting_staff_required, name="dispatch")
class CustomerCreateView(AccountingSectionMixin, CreateView):
    """
    Create a new customer.
    """
    section = "customer"
    model = Customer
    form_class = CustomerForm
    template_name = "accounting/customer/form.html"

    def get_success_url(self):
        return reverse("accounting:customer_list")


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerUpdateView(AccountingSectionMixin, UpdateView):
    """
    Update an existing customer.
    """
    section = "customer"
    model = Customer
    form_class = CustomerForm
    template_name = "accounting/customer/form.html"

    def get_success_url(self):
        return reverse("accounting:customer_list")


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerDeleteView(AccountingSectionMixin, DeleteView):
    """
    Delete a customer if no protected relations exist.
    If ProtectedError is raised, show a friendly message instead of 500.
    """
    section = "customer"
    model = Customer
    template_name = "accounting/customer/delete.html"
    success_url = reverse_lazy("accounting:customer_list")

    def post(self, request, *args, **kwargs):
        """
        Custom delete to catch ProtectedError and display a message instead.
        """
        self.object = self.get_object()
        try:
            self.object.delete()
        except ProtectedError:
            messages.error(
                request,
                "لا يمكن حذف هذا الزبون لأنه مرتبط بفواتير أو دفعات أو طلبات قائمة. "
                "يمكنك تعديل بياناته أو إبقاءه كما هو للسجلات المحاسبية."
            )
            return redirect("accounting:customer_detail", pk=self.object.pk)
        else:
            messages.success(request, "تم حذف الزبون بنجاح.")
            return redirect(self.success_url)


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerDetailView(AttachmentPanelMixin, AccountingSectionMixin, DetailView):
    """
    Customer full profile:
    - Invoices
    - Orders
    - Payments
    - Balance summary
    """
    section = "customers"  # عشان التاب في الناف بار يشتغل صح
    model = Customer
    template_name = "accounting/customer/detail.html"
    context_object_name = "customer"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # إضافة لوحة المرفقات للزبون الحالي
        ctx = self.inject_attachment_panel_context(ctx)

        customer = self.object

        # Invoices
        invoices = (
            customer.invoices.all()
            .order_by("-issued_at", "-id")
        )

        # Payments
        payments = (
            customer.payments.all()
            .select_related("invoice")
            .order_by("-date", "-id")
        )

        # Orders
        orders = (
            customer.orders.all()
            .prefetch_related("items__product")
            .order_by("-created_at", "id")
        )

        # Summary
        total_invoices = invoices.aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        total_paid = payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")

        ctx["invoices"] = invoices
        ctx["payments"] = payments
        ctx["orders"] = orders
        ctx["total_invoices"] = total_invoices
        ctx["total_paid"] = total_paid
        ctx["balance"] = total_invoices - total_paid

        return ctx


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerPaymentCreateView(AccountingSectionMixin, TodayInitialDateMixin, FormView):
    """
    Create a general payment for a customer (not bound to a specific invoice).
    URL: /accounting/customer/<pk>/payments/new/
    """
    section = "payments"
    template_name = "accounting/customer/payment.html"
    form_class = PaymentForInvoiceForm

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(Customer, pk=kwargs.get("pk"))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["customer"] = self.customer
        return ctx

    # get_initial from TodayInitialDateMixin

    def form_valid(self, form):
        payment = form.save(commit=False)
        payment.customer = self.customer
        payment.invoice = None  # General payment, not tied to invoice
        payment.save()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("accounting:customer_detail", kwargs={"pk": self.customer.pk})


# =====================================================================
# General payment allocation
# =====================================================================

@accounting_staff_required
def apply_general_payment(request, pk):
    """
    Allocate a general payment (invoice__isnull=True) to a specific invoice.

    Behaviour:
    - If applied amount == full payment amount:
        Attach the payment directly to the chosen invoice.
    - If applied amount < full payment amount:
        Create a new payment for the invoice and reduce
        the amount of the original general payment.
    """
    payment = get_object_or_404(
        Payment,
        pk=pk,
        invoice__isnull=True,
    )
    customer = payment.customer

    if not customer.invoices.exists():
        messages.error(request, "لا توجد فواتير لهذا الزبون لتسوية الدفعة عليها.")
        return redirect("accounting:customer_detail", pk=customer.pk)

    if request.method == "POST":
        form = ApplyPaymentForm(customer, payment.amount, request.POST)
        if form.is_valid():
            invoice = form.cleaned_data["invoice"]
            amount = form.cleaned_data["amount"]

            try:
                is_full, remaining, _new_payment = allocate_general_payment(
                    payment=payment,
                    invoice=invoice,
                    amount=amount,
                    partial_notes=f"تسوية جزء ({amount}) من الدفعة العامة #{payment.pk}",
                )
            except ValueError:
                messages.error(request, "قيمة التسوية غير صحيحة.")
                return redirect("accounting:customer_detail", pk=customer.pk)

            if is_full:
                messages.success(
                    request,
                    f"تم تسوية الدفعة بالكامل على الفاتورة {invoice.serial}.",
                )
            else:
                messages.success(
                    request,
                    f"تم تسوية مبلغ {amount} على الفاتورة {invoice.serial}، "
                    f"والمتبقي في الدفعة العامة هو {remaining}."
                )

            return redirect("accounting:customer_detail", pk=customer.pk)
    else:
        form = ApplyPaymentForm(customer, payment.amount)

    return render(
        request,
        "accounting/payment/payment_apply.html",
        {
            "payment": payment,
            "customer": customer,
            "form": form,
        },
    )


# ============================================================
# Orders (staff)
# ============================================================

@method_decorator(accounting_staff_required, name="dispatch")
class OrderListView(AccountingSectionMixin, ListView):
    """
    Staff list of orders.
    """
    section = "orders"
    model = Order
    template_name = "accounting/orders/list.html"
    context_object_name = "orders"
    paginate_by = 20

    def get_queryset(self):
        return (
            Order.objects
            .select_related("customer", "created_by", "confirmed_by")
            .prefetch_related("items__product")
            .order_by("-created_at", "id")
        )


@method_decorator(accounting_staff_required, name="dispatch")
class OrderDetailView(AttachmentPanelMixin, AccountingSectionMixin, DetailView):
    section = "orders"
    model = Order
    template_name = "accounting/orders/detail.html"
    context_object_name = "order"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx = self.inject_attachment_panel_context(ctx)
        return ctx



@method_decorator(accounting_staff_required, name="dispatch")
class OrderCreateView(AccountingSectionMixin, ProductJsonMixin, CreateView):
    """
    Create staff order with inline items formset.
    """
    section = "orders"
    model = Order
    form_class = OrderForm
    template_name = "accounting/orders/form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        if self.request.POST:
            ctx["item_formset"] = OrderItemFormSet(self.request.POST)
        else:
            ctx["item_formset"] = OrderItemFormSet()

        # Products JSON for JS
        ctx = self.inject_products_json(ctx)
        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        item_formset = context["item_formset"]

        if not item_formset.is_valid():
            return self.form_invalid(form)

        order = form.save(commit=False)
        order.created_by = self.request.user
        order.is_online = False  # staff-created order
        if not order.status:
            order.status = Order.STATUS_DRAFT
        order.save()
        self.object = order

        item_formset.instance = order
        item_formset.save()

        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("accounting:order_detail", kwargs={"pk": self.object.pk})


@method_decorator(accounting_staff_required, name="dispatch")
class OrderUpdateView(AccountingSectionMixin, ProductJsonMixin, UpdateView):
    """
    Update an existing staff order with items formset.
    """
    section = "orders"
    model = Order
    form_class = OrderForm
    template_name = "accounting/orders/form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = self.object

        if self.request.POST:
            ctx["item_formset"] = OrderItemFormSet(self.request.POST, instance=order)
        else:
            ctx["item_formset"] = OrderItemFormSet(instance=order)

        ctx = self.inject_products_json(ctx)
        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        item_formset = context["item_formset"]

        if not item_formset.is_valid():
            return self.form_invalid(form)

        order = form.save(commit=False)
        order.save()
        self.object = order

        item_formset.instance = order
        item_formset.save()

        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("accounting:order_detail", kwargs={"pk": self.object.pk})


@accounting_staff_required
def order_to_invoice(request, pk):
    """
    Convert an order into an invoice using the service layer.
    """
    order = get_object_or_404(
        Order.objects.select_related("customer").prefetch_related("items__product"),
        pk=pk,
    )

    # Already converted
    if getattr(order, "invoice", None):
        messages.info(
            request,
            _("تم تحويل هذا الطلب إلى فاتورة من قبل.")
        )
        return redirect("accounting:invoice_detail", serial=order.invoice.serial)

    # Only allow POST
    if request.method != "POST":
        return redirect("accounting:order_detail", pk=order.pk)

    # Use service to perform the conversion logic
    invoice = convert_order_to_invoice(order)

    # Audit log
    log_event(
        action=AuditLog.Action.CREATE,
        message=_("تم إنشاء فاتورة من الطلب رقم %(pk)s برقم فاتورة %(serial)s.") % {
            "pk": order.pk,
            "serial": invoice.serial,
        },
        actor=request.user,
        target=invoice,
        extra={
            "order_id": order.pk,
            "invoice_serial": invoice.serial,
            "source": "order_to_invoice",
        },
    )

    # Send notification to the customer if linked to a user
    customer_user = getattr(order.customer, "user", None)
    if customer_user is not None:
        create_notification(
            recipient=customer_user,
            verb=_("تم إنشاء فاتورة جديدة برقم %(serial)s من طلبك.") % {
                "serial": invoice.serial
            },
            target=invoice,
        )

    messages.success(
        request,
        _("تم إنشاء الفاتورة %(serial)s من هذا الطلب.") % {"serial": invoice.serial}
    )

    return redirect("accounting:invoice_detail", serial=invoice.serial)




@accounting_staff_required
def staff_order_confirm(request, pk):
    """
    Quick confirm button for orders.
    """
    order = get_object_or_404(Order, pk=pk)

    if request.method == "POST":
        if order.status != Order.STATUS_CONFIRMED:
            old_status = order.status

            order.status = Order.STATUS_CONFIRMED
            order.confirmed_by = request.user
            order.confirmed_at = timezone.now()
            order.save(update_fields=["status", "confirmed_by", "confirmed_at"])

            # Audit log: order status change
            log_event(
                action=AuditLog.Action.STATUS_CHANGE,
                message=f"تأكيد الطلب رقم {order.pk} (من {old_status} إلى {order.status}).",
                actor=request.user,
                target=order,
                extra={
                    "old_status": old_status,
                    "new_status": order.status,
                    "source": "staff_order_confirm",
                },
            )

            # Send notification to the customer if linked to a user
            customer_user = getattr(order.customer, "user", None)
            if customer_user is not None:
                create_notification(
                    recipient=customer_user,
                    verb=_("تم تأكيد طلبك رقم %(serial)s.") % {"serial": order.pk},
                    target=order,
                )

        return redirect("accounting:order_detail", pk=order.pk)

    # If GET, just redirect back
    return redirect("accounting:order_detail", pk=order.pk)




@method_decorator(accounting_staff_required, name="dispatch")
class OrderPrintView(AccountingSectionMixin, DetailView):
    """
    Print page for order (staff side).
    """
    section = "orders"
    model = Order
    template_name = "accounting/orders/print.html"
    context_object_name = "order"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("customer", "created_by", "confirmed_by")
            .prefetch_related("items__product")
        )


# ============================================================
# Payment print
# ============================================================

@method_decorator(accounting_staff_required, name="dispatch")
class PaymentPrintView(AccountingSectionMixin, DetailView):
    """
    Print page for payment receipt.
    """
    section = "payments"
    model = Payment
    template_name = "accounting/payment/print.html"
    context_object_name = "payment"


# ============================================================
# Payment List
# ============================================================

@method_decorator(accounting_staff_required, name="dispatch")
class PaymentListView(AccountingSectionMixin, ListView):
    section = "payments"
    model = Payment
    template_name = "accounting/payment/list.html"
    context_object_name = "payments"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related("customer", "invoice")
            .order_by("-date", "-id")
        )

        # Optional filters
        customer = self.request.GET.get("customer")
        if customer:
            qs = qs.filter(customer__name__icontains=customer)

        method = self.request.GET.get("method")
        if method:
            qs = qs.filter(method=method)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["method_filter"] = self.request.GET.get("method", "")
        ctx["customer_filter"] = self.request.GET.get("customer", "")
        return ctx


# ============================================================
# Payment Create
# ============================================================

@method_decorator(accounting_staff_required, name="dispatch")
class PaymentCreateView(AccountingSectionMixin, TodayInitialDateMixin, CreateView):
    """
    إضافة دفعة جديدة من شاشة عامة.
    يمكن ربطها بفاتورة أو تركها دفعة عامة (بدون فاتورة).
    """
    section = "payments"
    model = Payment
    form_class = PaymentForm
    template_name = "accounting/payment/form.html"

    def get_success_url(self):
        return reverse("accounting:payment_list")


# ============================================================
# Payment Update and reconciliation
# ============================================================

@method_decorator(accounting_staff_required, name="dispatch")
class PaymentUpdateView(AccountingSectionMixin, UpdateView):
    """
    تعديل دفعة موجودة:
    - نسمح بتعديل التاريخ، المبلغ، طريقة الدفع، الملاحظات، وربط/فك الفاتورة.
    - نثبّت العميل (لا يتغير من شاشة التعديل).
    """
    section = "payments"
    model = Payment
    form_class = PaymentForm
    template_name = "accounting/payment/form.html"
    context_object_name = "payment"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        # تثبيت العميل فقط (لا يتغير)
        if "customer" in form.fields:
            form.fields["customer"].disabled = True

        # الفاتورة: نسمح بالتعديل/المسح، لكن نفلترها على فواتير نفس العميل
        if "invoice" in form.fields:
            form.fields["invoice"].queryset = Invoice.objects.filter(
                customer=self.object.customer
            )
            form.fields["invoice"].required = False  # مسموح تكون فاضية (دفعة عامة)

        return form

    def get_success_url(self):
        return reverse("accounting:payment_list")


@login_required
@permission_required("accounting.change_invoice", raise_exception=True)
def invoice_confirm_view(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    if invoice.status != Invoice.Status.DRAFT:
        messages.error(request, "لا يمكن اعتماد إلا الفواتير في حالة مسودة.")
        return redirect("accounting:invoice_detail", serial=invoice.serial)

    old_status = invoice.status

    # Change status to SENT
    invoice.status = Invoice.Status.SENT
    invoice.save(update_fields=["status"])

    try:
        entry = invoice.post_to_ledger()
    except Exception as e:
        # Roll back to DRAFT if posting fails
        invoice.status = Invoice.Status.DRAFT
        invoice.save(update_fields=["status"])
        messages.error(request, f"تعذّر ترحيل الفاتورة إلى دفتر الأستاذ: {e}")

        log_event(
            action=AuditLog.Action.OTHER,
            message=f"فشل ترحيل الفاتورة {invoice.serial} إلى دفتر الأستاذ: {e}",
            actor=request.user,
            target=invoice,
            extra={"error": str(e), "source": "invoice_confirm_view"},
        )

        return redirect("accounting:invoice_detail", serial=invoice.serial)

    # Audit log - success
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=f"اعتماد الفاتورة {invoice.serial} وترحيلها إلى دفتر الأستاذ (قيد: {entry.serial}).",
        actor=request.user,
        target=invoice,
        extra={
            "old_status": old_status,
            "new_status": invoice.status,
            "journal_entry_number": entry.serial,
            "source": "invoice_confirm_view",
        },
    )

    # Send notification to the customer if linked to a user
    customer_user = getattr(invoice.customer, "user", None)
    if customer_user is not None:
        create_notification(
            recipient=customer_user,
            verb=_(
                "تم اعتماد فاتورتك رقم %(serial)s وترحيلها في النظام."
            ) % {"serial": invoice.serial},
            target=invoice,
        )

    messages.success(
        request,
        f"تم اعتماد الفاتورة وترحيلها بنجاح (قيد: {entry.serial})."
    )
    return redirect("accounting:invoice_detail", serial=invoice.serial)




@login_required
@permission_required("accounting.change_invoice", raise_exception=True)
def invoice_unpost_view(request, pk):
    """
    إلغاء ترحيل الفاتورة:
    - إنشاء قيد عكسي في دفتر الأستاذ
    - فك الربط مع الفاتورة
    - إعادة حالة الفاتورة إلى DRAFT
    """
    invoice = get_object_or_404(Invoice, pk=pk)

    if invoice.ledger_entry is None:
        messages.error(request, "لا يوجد قيد مرحّل مرتبط بهذه الفاتورة.")
        return redirect("accounting:invoice_detail", serial=invoice.serial)

    if invoice.paid_amount and invoice.paid_amount > 0:
        messages.error(request, "لا يمكن إلغاء الترحيل لفاتورة عليها دفعات.")
        return redirect("accounting:invoice_detail", serial=invoice.serial)

    old_status = invoice.status

    try:
        reversal_entry = invoice.unpost_from_ledger(user=request.user)
    except Exception as e:
        messages.error(request, f"تعذّر إلغاء الترحيل: {e}")

        log_event(
            action=AuditLog.Action.OTHER,
            message=f"فشل إلغاء ترحيل الفاتورة {invoice.serial}: {e}",
            actor=request.user,
            target=invoice,
            extra={"error": str(e), "source": "invoice_unpost_view"},
        )

        return redirect("accounting:invoice_detail", serial=invoice.serial)

    # Audit log success
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=f"إلغاء ترحيل الفاتورة {invoice.serial} وإنشاء قيد عكسي {reversal_entry.serial}.",
        actor=request.user,
        target=invoice,
        extra={
            "old_status": old_status,
            "new_status": invoice.status,
            "reversal_entry_number": reversal_entry.serial,
            "source": "invoice_unpost_view",
        },
    )

    messages.success(
        request,
        f"تم إنشاء قيد عكسي ({reversal_entry.serial}) وإعادة الفاتورة إلى حالة مسودة."
    )
    return redirect("accounting:invoice_detail", serial=invoice.serial)




@staff_member_required
def accounting_settings_view(request):
    """
    Simple view to edit global sales/invoice settings.

    المنطق الخاص بترقيم الفواتير (NumberingScheme في core)
    يتم تحديثه داخل Settings.save حتى يكون عندنا مصدر واحد للحقيقة.
    """
    settings_obj = Settings.get_solo()

    if request.method == "POST":
        form = SettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()  # Settings.save يتولى مزامنة NumberingScheme
            messages.success(request, _("تم تحديث إعدادات المبيعات والترقيم بنجاح."))
            return redirect("accounting:sales_settings")
    else:
        form = SettingsForm(instance=settings_obj)

    context = {
        "form": form,
        "accounting_section": "settings",
    }
    return render(request, "accounting/settings/settings.html", context)




