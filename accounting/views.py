# accounting/views.py
import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
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

from website.models import Product
from .forms import (
    InvoiceForm,
    PaymentForInvoiceForm,
    CustomerForm,
    InvoiceItemFormSet,
    ApplyPaymentForm,
    OrderItemFormSet,
    OrderForm, PaymentForm,
)
from .models import Invoice, Payment, Customer, Order, InvoiceItem


# ============================================================
# Default invoice terms template
# ============================================================

DEFAULT_INVOICE_TERMS = (
    "• تُصدر هذه الفاتورة وفقًا لشروط مزون ألمنيوم.\n"
    "• يجب سداد المبلغ خلال 15 يومًا من تاريخ الفاتورة ما لم يُتفق على غير ذلك كتابيًا.\n"
    "• تحتفظ مزون ألمنيوم بحقها في إيقاف التوريد أو الخدمات في حال التأخر عن السداد.\n"
    "• في حال وجود أي ملاحظة على الفاتورة، يرجى التواصل خلال 3 أيام عمل من تاريخ الاستلام.\n"
)


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
# Invoices
# ============================================================

@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceListView(ListView):
    """
    Staff list of invoices with optional status filter.
    """
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
    """
    Create a new invoice with inline items formset.
    """
    model = Invoice
    form_class = InvoiceForm
    template_name = "accounting/invoice_form.html"

    def get_initial(self):
        initial = super().get_initial()

        # Pre-fill customer if passed in query params
        customer_id = self.request.GET.get("customer")
        if customer_id:
            initial["customer"] = customer_id

        # Pre-fill default terms template for new invoices
        if "terms" not in initial or not initial.get("terms"):
            initial["terms"] = DEFAULT_INVOICE_TERMS

        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # Invoice items formset
        if self.request.POST:
            ctx["item_formset"] = InvoiceItemFormSet(self.request.POST)
        else:
            ctx["item_formset"] = InvoiceItemFormSet()

        # Products JSON for JS auto-fill (description + price)
        products = Product.objects.filter(is_active=True)
        ctx["products_json"] = mark_safe(json.dumps(
            {
                str(p.id): {
                    "description": p.description or "",
                    "price": str(p.price),
                }
                for p in products
            }
        ))

        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        item_formset = context["item_formset"]

        # Validate formset first
        if not item_formset.is_valid():
            return self.form_invalid(form)

        # 1) Save invoice without total
        invoice = form.save(commit=False)
        invoice.total_amount = Decimal("0")
        invoice.save()  # number is generated in model's save()
        self.object = invoice

        # 2) Save items
        item_formset.instance = invoice
        item_formset.save()

        # 3) Compute total from items
        total = sum((item.subtotal for item in invoice.items.all()), Decimal("0"))
        invoice.total_amount = total
        invoice.save(update_fields=["total_amount"])

        # 4) Redirect
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("accounting:invoice_list")


@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceUpdateView(UpdateView):
    """
    Update existing invoice + related items.
    """
    model = Invoice
    form_class = InvoiceForm
    template_name = "accounting/invoice_form.html"
    slug_field = "number"
    slug_url_kwarg = "number"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        invoice = self.object

        # Bind formset to existing invoice
        if self.request.POST:
            ctx["item_formset"] = InvoiceItemFormSet(self.request.POST, instance=invoice)
        else:
            ctx["item_formset"] = InvoiceItemFormSet(instance=invoice)

        # Same products JSON used in create
        products = Product.objects.filter(is_active=True)
        ctx["products_json"] = mark_safe(json.dumps(
            {
                str(p.id): {
                    "description": p.description or "",
                    "price": str(p.price),
                }
                for p in products
            }
        ))

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
        return reverse("accounting:invoice_detail", kwargs={"number": self.object.number})


@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceDetailView(DetailView):
    """
    Staff invoice detail page (with items, payments, etc).
    """
    model = Invoice
    template_name = "accounting/invoice_detail.html"
    context_object_name = "invoice"
    slug_field = "number"
    slug_url_kwarg = "number"


@method_decorator(accounting_staff_required, name="dispatch")
class InvoicePaymentCreateView(FormView):
    """
    Create a payment for a specific invoice.
    URL: /accounting/invoices/<number>/payments/new/
    """
    template_name = "accounting/invoice_payment_form.html"
    form_class = PaymentForInvoiceForm

    def dispatch(self, request, *args, **kwargs):
        # Load invoice once and store on self
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
        initial.setdefault("date", timezone.now().date())
        return initial

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
            kwargs={"number": self.invoice.number},
        )


@method_decorator(accounting_staff_required, name="dispatch")
class InvoicePrintView(DetailView):
    """
    Print page for invoice (staff side).
    """
    model = Invoice
    template_name = "accounting/invoice_print.html"
    context_object_name = "invoice"
    slug_field = "number"
    slug_url_kwarg = "number"


# ============================================================
# Dashboard
# ============================================================

@method_decorator(accounting_staff_required, name="dispatch")
class AccountingDashboardView(TemplateView):
    """
    Main accounting dashboard:
    - Counters
    - Recent invoices, payments, orders
    - Pending orders (no invoice)
    - Unpaid invoices
    """
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
class CustomerListView(ListView):
    """
    Staff list of customers, with simple search by name/company.
    """
    model = Customer
    template_name = "accounting/customer_list.html"
    context_object_name = "customers"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(
                Q(name__icontains=q) | Q(company_name__icontains=q)
            )
        return qs


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerCreateView(CreateView):
    """
    Create a new customer.
    """
    model = Customer
    form_class = CustomerForm
    template_name = "accounting/customer_form.html"

    def get_success_url(self):
        return reverse("accounting:customer_list")


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerUpdateView(UpdateView):
    """
    Update an existing customer.
    """
    model = Customer
    form_class = CustomerForm
    template_name = "accounting/customer_form.html"

    def get_success_url(self):
        return reverse("accounting:customer_list")


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerDeleteView(DeleteView):
    """
    Delete a customer if no protected relations exist.
    If ProtectedError is raised, show a friendly message instead of 500.
    """
    model = Customer
    template_name = "accounting/customer_confirm_delete.html"
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
class CustomerDetailView(DetailView):
    """
    Customer full profile:
    - Invoices
    - Orders
    - Payments
    - Balance summary
    """
    model = Customer
    template_name = "accounting/customer_detail.html"
    context_object_name = "customer"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
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
class CustomerPaymentCreateView(FormView):
    """
    Create a general payment for a customer (not bound to a specific invoice).
    URL: /accounting/customers/<pk>/payments/new/
    """
    template_name = "accounting/customer_payment_form.html"
    form_class = PaymentForInvoiceForm

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(Customer, pk=kwargs.get("pk"))
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial.setdefault("date", timezone.now().date())
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["customer"] = self.customer
        return ctx

    def form_valid(self, form):
        payment = form.save(commit=False)
        payment.customer = self.customer
        payment.invoice = None  # General payment, not tied to invoice
        payment.save()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("accounting:customer_detail", kwargs={"pk": self.customer.pk})


# ============================================================
# General payment allocation
# ============================================================

@accounting_staff_required
def apply_general_payment(request, pk):
    """
    Apply a general payment (invoice__isnull=True) to a specific invoice.

    - If applied amount equals full payment → attach payment directly to invoice.
    - If applied amount is partial          → create new payment for invoice
                                             and reduce amount on original one.
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

            # Full allocation
            if amount == payment.amount:
                payment.invoice = invoice
                payment.save(update_fields=["invoice"])
                messages.success(
                    request,
                    f"تم تسوية الدفعة بالكامل على الفاتورة {invoice.number}.",
                )
            else:
                # Partial allocation
                Payment.objects.create(
                    customer=customer,
                    invoice=invoice,
                    amount=amount,
                    date=payment.date,
                    method=payment.method,
                    notes=f"تسوية جزء ({amount}) من الدفعة العامة #{payment.pk}",
                )
                payment.amount = payment.amount - amount
                payment.save(update_fields=["amount"])

                messages.success(
                    request,
                    f"تم تسوية مبلغ {amount} على الفاتورة {invoice.number}، "
                    f"والمتبقي في الدفعة العامة هو {payment.amount}."
                )

            return redirect("accounting:customer_detail", pk=customer.pk)
    else:
        form = ApplyPaymentForm(customer, payment.amount)

    return render(
        request,
        "accounting/general_payment_apply.html",
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
class OrderListView(ListView):
    """
    Staff list of orders.
    """
    model = Order
    template_name = "accounting/orders/order_list.html"
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
class OrderDetailView(DetailView):
    """
    Staff order detail page.
    """
    model = Order
    template_name = "accounting/orders/order_detail.html"
    context_object_name = "order"


@method_decorator(accounting_staff_required, name="dispatch")
class OrderCreateView(CreateView):
    """
    Create staff order with inline items formset.
    """
    model = Order
    form_class = OrderForm
    template_name = "accounting/orders/order_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        if self.request.POST:
            ctx["item_formset"] = OrderItemFormSet(self.request.POST)
        else:
            ctx["item_formset"] = OrderItemFormSet()

        # Products JSON for JS
        products = Product.objects.filter(is_active=True)
        ctx["products_json"] = mark_safe(json.dumps(
            {
                str(p.id): {
                    "description": p.description or "",
                    "price": str(p.price),
                }
                for p in products
            }
        ))
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
class OrderUpdateView(UpdateView):
    """
    Update an existing staff order with items formset.
    """
    model = Order
    form_class = OrderForm
    template_name = "accounting/orders/order_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = self.object

        if self.request.POST:
            ctx["item_formset"] = OrderItemFormSet(self.request.POST, instance=order)
        else:
            ctx["item_formset"] = OrderItemFormSet(instance=order)

        products = Product.objects.filter(is_active=True)
        ctx["products_json"] = mark_safe(json.dumps(
            {
                str(p.id): {
                    "description": p.description or "",
                    "price": str(p.price),
                }
                for p in products
            }
        ))
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
    Convert an order to an invoice:
    - Create invoice from order data.
    - Copy all order items to invoice items.
    - Link order to invoice (order.invoice).
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
        return redirect("accounting:invoice_detail", number=order.invoice.number)

    # Only allow POST
    if request.method != "POST":
        return redirect("accounting:order_detail", pk=order.pk)

    # Create invoice
    invoice = Invoice(
        customer=order.customer,
        status=Invoice.Status.DRAFT,
        description=order.notes or "",
        terms=DEFAULT_INVOICE_TERMS,
        issued_at=timezone.now(),
    )
    invoice.total_amount = Decimal("0")
    invoice.save()  # number will be generated automatically

    # Create invoice items from order items
    total = Decimal("0")
    invoice_items = []
    for item in order.items.all():
        inv_item = InvoiceItem(
            invoice=invoice,
            product=item.product,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
        )
        invoice_items.append(inv_item)
        total += inv_item.subtotal

    InvoiceItem.objects.bulk_create(invoice_items)

    # Update invoice total
    invoice.total_amount = total
    invoice.save(update_fields=["total_amount"])

    # Link order to invoice and mark as confirmed if constant exists
    order.invoice = invoice
    try:
        order.status = Order.STATUS_CONFIRMED
        order.save(update_fields=["invoice", "status"])
    except AttributeError:
        order.save(update_fields=["invoice"])

    messages.success(
        request,
        _("تم إنشاء الفاتورة %(number)s من هذا الطلب.") % {"number": invoice.number}
    )

    return redirect("accounting:invoice_detail", number=invoice.number)


@accounting_staff_required
def staff_order_confirm(request, pk):
    """
    Quick confirm button for orders.
    """
    order = get_object_or_404(Order, pk=pk)

    if request.method == "POST":
        if order.status != Order.STATUS_CONFIRMED:
            order.status = Order.STATUS_CONFIRMED
            order.confirmed_by = request.user
            order.confirmed_at = timezone.now()
            order.save(update_fields=["status", "confirmed_by", "confirmed_at"])
        return redirect("accounting:order_detail", pk=order.pk)

    # If GET, just redirect back
    return redirect("accounting:order_detail", pk=order.pk)


@method_decorator(accounting_staff_required, name="dispatch")
class OrderPrintView(DetailView):
    """
    Print page for order (staff side).
    """
    model = Order
    template_name = "accounting/orders/order_print.html"
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
class PaymentPrintView(DetailView):
    """
    Print page for payment receipt.
    """
    model = Payment
    template_name = "accounting/payment_print.html"
    context_object_name = "payment"

# ============================================================
# Payment List
# ============================================================
@method_decorator(accounting_staff_required, name="dispatch")
class PaymentListView(ListView):
    model = Payment
    template_name = "accounting/payment_list.html"
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
class PaymentCreateView(CreateView):
    """
    إضافة دفعة جديدة من شاشة عامة.
    يمكن ربطها بفاتورة أو تركها دفعة عامة (بدون فاتورة).
    """
    model = Payment
    form_class = PaymentForm
    template_name = "accounting/payment_form.html"

    def get_initial(self):
        initial = super().get_initial()
        # تاريخ اليوم كقيمة افتراضية
        initial.setdefault("date", timezone.now().date())
        return initial

    def get_success_url(self):
        return reverse("accounting:payment_list")

# ============================================================
# Payment Update and reconciliation
# ============================================================
@method_decorator(accounting_staff_required, name="dispatch")
class PaymentUpdateView(UpdateView):
    """
    تعديل دفعة موجودة:
    - نسمح بتعديل التاريخ، المبلغ، طريقة الدفع، الملاحظات، وربط/فك الفاتورة.
    - نثبّت العميل (لا يتغير من شاشة التعديل).
    """
    model = Payment
    form_class = PaymentForm
    template_name = "accounting/payment_form.html"
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

