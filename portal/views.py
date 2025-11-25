# portal/views.py

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import (
    TemplateView,
    ListView,
    DetailView,
    UpdateView,
    FormView,
)
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from accounting.forms import CustomerProfileForm, CustomerOrderForm
from accounting.models import  Invoice, Order, OrderItem
from cart.cart import Cart
from contacts.models import Contact
from core.services.notifications import create_notification
from payments.models import Payment
from website.models import Product


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

def get_portal_customer_or_403(user) -> Contact:
    """
    Central helper to fetch the Customer linked to the given user.

    - Raises PermissionDenied if:
      * user is not authenticated, or
      * user is authenticated but has no related Customer.
    This keeps all permission logic in one place.
    """
    if not user.is_authenticated:
        # We normally use redirect_to_login in views,
        # but here we raise PermissionDenied for safety if called directly.
        raise PermissionDenied(_("يجب تسجيل الدخول للوصول إلى بوابة الزبون."))

    try:
        return Contact.objects.select_related("user").get(user=user)
    except Contact.DoesNotExist:
        # Logged-in user but no customer profile linked → forbidden.
        raise PermissionDenied(_("لا يوجد حساب زبون مرتبط بهذا المستخدم."))


# ------------------------------------------------------------------------------
# Mixins
# ------------------------------------------------------------------------------

class CustomerPortalMixin:
    """
    Base mixin for all customer-portal views.

    Responsibilities:
    - Ensure the user is authenticated.
    - Load the related Customer instance and store it in `self.customer`.
    - If user is not authenticated → redirect to login.
    - If no related Customer → raise PermissionDenied (403).
    """

    customer: Contact | None = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            # Keep using redirect_to_login to respect LOGIN_URL settings.
            return redirect_to_login(request.get_full_path())

        # Shared helper to centralize the logic and error messages.
        self.customer = get_portal_customer_or_403(request.user)
        return super().dispatch(request, *args, **kwargs)


class CustomerInvoiceQuerysetMixin(CustomerPortalMixin):
    """
    Mixin that restricts invoice queries to the current portal customer
    and prefetches related items/product for performance.
    """

    def get_queryset(self):
        return (
            Invoice.objects
            .filter(customer=self.customer)
            .prefetch_related("items__product")  # adjust related_name if needed
            .order_by("-issued_at", "-id")
        )


class CustomerPaymentQuerysetMixin(CustomerPortalMixin):
    """
    Mixin that provides a queryset of payments filtered by the current customer.
    """

    def get_queryset(self):
        return (
            Payment.objects
            .filter(customer=self.customer)
            .select_related("invoice")
            .order_by("-date", "-id")
        )


class CustomerOrderQuerysetMixin(CustomerPortalMixin):
    """
    Mixin that provides a queryset of orders filtered by the current customer.
    """

    def get_queryset(self):
        return (
            Order.objects
            .filter(customer=self.customer)
            .order_by("-created_at", "-id")
        )


# ------------------------------------------------------------------------------
# Dashboard / Profile
# ------------------------------------------------------------------------------

class PortalDashboardView(CustomerPortalMixin, TemplateView):
    """
    Simple dashboard summary for the customer:
    - Number of invoices and payments
    - Total invoiced, total paid, current balance
    - Recent invoices and payments
    """
    template_name = "portal/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        customer = self.customer

        invoices_qs = (
            Invoice.objects
            .filter(customer=customer)
            .order_by("-issued_at", "-id")
        )
        payments_qs = (
            Payment.objects
            .filter(customer=customer)
            .order_by("-date", "-id")
        )

        total_invoices = invoices_qs.aggregate(s=Sum("total_amount"))["s"] or 0
        total_paid = payments_qs.aggregate(s=Sum("amount"))["s"] or 0

        ctx.update(
            customer=customer,
            invoice_count=invoices_qs.count(),
            payment_count=payments_qs.count(),
            total_invoices=total_invoices,
            total_paid=total_paid,
            balance=total_invoices - total_paid,
            recent_invoices=invoices_qs[:5],
            recent_payments=payments_qs[:5],
        )
        return ctx


class PortalProfileUpdateView(CustomerPortalMixin, UpdateView):
    """
    Allow the current portal customer to update their profile information.
    """
    model = Contact
    form_class = CustomerProfileForm
    template_name = "portal/profile/form.html"
    context_object_name = "customer"

    def get_object(self, queryset=None):
        """
        Always return the bound customer for the current logged-in user.
        """
        return self.customer

    def form_valid(self, form):
        """
        After successfully saving the profile, add a success flash message.
        """
        response = super().form_valid(form)
        messages.success(
            self.request,
            _("تم تحديث بيانات حسابك بنجاح.")
        )
        return response

    def get_success_url(self):
        """
        Redirect back to the portal dashboard (or profile page if you prefer).
        """
        from django.urls import reverse
        return reverse("portal:dashboard")


# ------------------------------------------------------------------------------
# Invoices / Payments (Portal)
# ------------------------------------------------------------------------------

class PortalInvoiceListView(CustomerInvoiceQuerysetMixin, ListView):
    """
    List all invoices for the current customer.
    """
    model = Invoice
    template_name = "portal/invoice/list.html"
    context_object_name = "invoices"
    paginate_by = 20


class PortalInvoiceDetailView(CustomerInvoiceQuerysetMixin, DetailView):
    """
    Show an invoice details (including items) for the current customer.
    Access is restricted by CustomerInvoiceQuerysetMixin.
    """
    model = Invoice
    template_name = "portal/invoice/detail.html"
    context_object_name = "invoice"
    slug_field = "serial"        # ✅ نستخدم serial
    slug_url_kwarg = "serial"    # ✅ اسم المتغيّر في الـ URL



class PortalInvoicePrintView(CustomerInvoiceQuerysetMixin, DetailView):
    """
    Print view for an invoice from the customer portal.
    Uses the same template as the accounting print view.
    """
    model = Invoice
    template_name = "accounting/invoices/print.html"
    context_object_name = "invoice"
    slug_field = "serial"        # ✅ نفس الشي
    slug_url_kwarg = "serial"


class PortalPaymentListView(CustomerPaymentQuerysetMixin, ListView):
    """
    List all payments made by the current customer.
    """
    model = Payment
    template_name = "portal/payment/list.html"
    context_object_name = "payments"
    paginate_by = 20


# ------------------------------------------------------------------------------
# Orders (Portal listing / detail)
# ------------------------------------------------------------------------------

class PortalOrderListView(CustomerOrderQuerysetMixin, ListView):
    """
    List all orders for the current customer.
    """
    model = Order
    template_name = "portal/orders/list.html"
    context_object_name = "orders"
    paginate_by = 20


class PortalOrderDetailView(CustomerOrderQuerysetMixin, DetailView):
    """
    Show the details of a single order for the current customer.
    """
    model = Order
    template_name = "portal/orders/detail.html"
    context_object_name = "order"

    def get_queryset(self):
        # Extend the queryset from the mixin with prefetch for items/product.
        return (
            super()
            .get_queryset()
            .prefetch_related("items__product")
        )


# ------------------------------------------------------------------------------
# Orders creation (single product) — CBV
# ------------------------------------------------------------------------------

class PortalOrderCreateView(CustomerPortalMixin, FormView):
    """
    Create a new order from a single product ("Order Now" button).

    Flow:
    - Load the product by `product_id` from the URL.
    - Use CustomerOrderForm to collect quantity and notes.
    - Create an Order with is_online=True.
    - Create a single OrderItem for the selected product.

    ملاحظة:
    - إرسال الإشعارات للستاف يتم عبر signals على موديل Order،
      وليس من داخل هذا الفيو.
    """

    form_class = CustomerOrderForm
    template_name = "portal/orders/create.html"
    success_url = reverse_lazy("portal:order_list")

    def dispatch(self, request, *args, **kwargs):
        """
        Load the product once and keep it on `self.product`.
        """
        self.product = get_object_or_404(
            Product,
            pk=kwargs.get("product_id"),
            is_active=True,
        )
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        """
        Provide a sensible default quantity of 1 if none is given.
        """
        initial = super().get_initial()
        initial.setdefault("quantity", 1)
        return initial

    def get_context_data(self, **kwargs):
        """
        Add the product to the context so the template can display its details.
        """
        ctx = super().get_context_data(**kwargs)
        ctx["product"] = self.product
        return ctx

    def form_valid(self, form):
        """
        On valid form:
        - Create the Order and its single OrderItem inside an atomic transaction.
        - Show a success message.
        - إشعارات الستاف تتم في signal على Order (عند الإنشاء).
        """
        customer = self.customer
        quantity = form.cleaned_data["quantity"]
        notes = form.cleaned_data.get("notes", "")

        with transaction.atomic():
            order = Order.objects.create(
                customer=customer,
                created_by=self.request.user,
                status=Order.STATUS_PENDING,
                is_online=True,
                notes=notes,
            )
            OrderItem.objects.create(
                order=order,
                product=self.product,
                quantity=quantity,
                unit_price=self.product.price,
            )
            # لو احتجت تستخدمه لاحقاً (مثلاً في مكسينز)
            self.object = order

        messages.success(
            self.request,
            _("تم إرسال طلبك بنجاح، وسيقوم الموظف بمراجعته وتأكيده."),
        )
        return HttpResponseRedirect(self.get_success_url())


# ------------------------------------------------------------------------------
# Cart checkout → Order (Portal) — CBV
# ------------------------------------------------------------------------------

class CartCheckoutView(CustomerPortalMixin, View):
    """
    Convert the current cart contents into a single Order for the customer.

    Behavior:
    - If the cart is empty → show error message and redirect to cart detail.
    - On POST:
        * Create an Order with is_online=True.
        * Create OrderItem for each cart line.
        * Clear the cart.
        * Redirect to the order detail page.
    - On GET:
        * Redirect back to the cart detail (no confirmation page here).
    """

    def _get_cart(self, request) -> Cart:
        """
        Small helper to initialize the Cart object.
        """
        return Cart(request)

    def get(self, request, *args, **kwargs):
        """
        For safety, we keep GET as a redirect back to cart detail.
        The actual creation is done via POST.
        """
        return redirect("cart:detail")

    def post(self, request, *args, **kwargs):
        cart = self._get_cart(request)
        if cart.is_empty():
            messages.error(request, _("سلتك فارغة."))
            return redirect("cart:detail")

        customer = self.customer

        with transaction.atomic():
            order = Order.objects.create(
                customer=customer,
                created_by=request.user,
                status=Order.STATUS_PENDING,
                is_online=True,
            )
            for item in cart:
                # We assume each `item` dict contains `product`, `quantity`, `price`.
                OrderItem.objects.create(
                    order=order,
                    product=item["product"],
                    quantity=item["quantity"],
                    unit_price=item["price"],
                )

            # 🔔 إرسال تنبيه لكل الموظفين عن طلب جديد من السلة
            staff_users = User.objects.filter(is_staff=True, is_active=True)
            for staff in staff_users:
                create_notification(
                    recipient=staff,
                    verb=_("تم إنشاء طلب جديد من سلة المشتريات في بوابة الزبون."),
                    target=order,
                )

        cart.clear()
        messages.success(request, _("تم إنشاء الطلب من السلة بنجاح."))
        return redirect("portal:order_detail", pk=order.pk)

