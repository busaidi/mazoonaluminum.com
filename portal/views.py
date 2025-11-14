# portal/views.py

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import TemplateView, ListView, DetailView, UpdateView

from accounting.forms import CustomerProfileForm, CustomerOrderForm
from accounting.models import Customer, Invoice, Payment, Order, OrderItem
from cart.cart import Cart
from website.models import Product


# ------------------------------------------------------------------------------
# Helpers / Mixins
# ------------------------------------------------------------------------------

class CustomerPortalMixin:
    """
    Mixin لكل الفيوز في بوابة الزبون:
    - يتأكد أن المستخدم مسجّل دخول
    - يجلب Customer المرتبط به (customer_profile)
    - يخزنه في self.customer لاستخدامه في بقية الميثودز
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        try:
            # Customer مرتبط بالمستخدم عبر OneToOneField user
            self.customer = Customer.objects.select_related("user").get(user=request.user)
        except Customer.DoesNotExist:
            # المستخدم مسجّل دخول لكن ليس لديه Customer مرتبط
            raise PermissionDenied("لا يوجد حساب زبون مرتبط بهذا المستخدم.")

        return super().dispatch(request, *args, **kwargs)


# ------------------------------------------------------------------------------
# Dashboard / Profile
# ------------------------------------------------------------------------------

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


class PortalProfileUpdateView(CustomerPortalMixin, UpdateView):
    """
    يسمح للزبون بتحديث بياناته (Customer المرتبط به).
    """
    model = Customer
    form_class = CustomerProfileForm
    template_name = "portal/profile_form.html"
    context_object_name = "customer"

    def get_object(self, queryset=None):
        # نستخدم self.customer من الـ mixin
        return self.customer

    def get_success_url(self):
        from django.urls import reverse
        return reverse("portal:dashboard")


# ------------------------------------------------------------------------------
# Invoices / Payments (Portal)
# ------------------------------------------------------------------------------

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


# ------------------------------------------------------------------------------
# Orders (Portal listing / detail)
# ------------------------------------------------------------------------------

class PortalOrderListView(CustomerPortalMixin, ListView):
    model = Order
    template_name = "portal/order_list.html"
    context_object_name = "orders"
    paginate_by = 20

    def get_queryset(self):
        return (
            Order.objects
            .filter(customer=self.customer)
            .order_by("-created_at", "-id")
        )


class PortalOrderDetailView(CustomerPortalMixin, DetailView):
    model = Order
    template_name = "portal/order_detail.html"
    context_object_name = "order"

    def get_queryset(self):
        # لا نسمح إلا بطلبات هذا الزبون
        return (
            Order.objects
            .filter(customer=self.customer)
            .prefetch_related("items__product")
        )


# ------------------------------------------------------------------------------
# Orders creation (single product / cart checkout)
# ------------------------------------------------------------------------------

@login_required
def portal_order_create(request, product_id):
    """
    إنشاء طلب جديد من صفحة منتج واحد (زر "اطلب الآن").
    يربط الطلب بالزبون الحالي (customer_profile) ويضبط is_online=True.
    """
    try:
        customer = request.user.customer_profile
    except Customer.DoesNotExist:
        raise PermissionDenied("لا يوجد حساب زبون مرتبط بهذا المستخدم.")

    product = get_object_or_404(Product, pk=product_id, is_active=True)

    if request.method == "POST":
        form = CustomerOrderForm(request.POST)
        if form.is_valid():
            quantity = form.cleaned_data["quantity"]
            notes = form.cleaned_data["notes"]

            with transaction.atomic():
                order = Order.objects.create(
                    customer=customer,
                    created_by=request.user,
                    status=Order.STATUS_PENDING,
                    is_online=True,
                    notes=notes,
                )
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    unit_price=product.price,
                )

            messages.success(
                request,
                "تم إرسال طلبك بنجاح، وسيقوم الموظف بمراجعته وتأكيده.",
            )
            return redirect("portal:order_list")
    else:
        form = CustomerOrderForm(initial={"quantity": 1})

    return render(
        request,
        "portal/orders/portal_order_create.html",
        {
            "form": form,
            "product": product,
        },
    )


@login_required
def cart_checkout(request):
    """
    تحويل محتوى السلة (Cart) إلى طلب واحد مرتبط بالزبون الحالي.
    """
    cart = Cart(request)
    if cart.is_empty():
        messages.error(request, "سلتك فارغة.")
        return redirect("cart:detail")

    try:
        customer = request.user.customer_profile
    except Customer.DoesNotExist:
        raise PermissionDenied("لا يوجد حساب زبون مرتبط بهذا المستخدم.")

    if request.method == "POST":
        with transaction.atomic():
            order = Order.objects.create(
                customer=customer,
                created_by=request.user,
                status=Order.STATUS_PENDING,
                is_online=True,
            )
            for item in cart:
                OrderItem.objects.create(
                    order=order,
                    product=item["product"],
                    quantity=item["quantity"],
                    unit_price=item["price"],
                )

        cart.clear()
        messages.success(request, "تم إنشاء الطلب من السلة بنجاح.")
        return redirect("portal:order_detail", pk=order.pk)

    # لو لم يكن POST نرجعه للسلة
    return redirect("cart:detail")
