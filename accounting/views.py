# accounting/views.py
import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Sum, Q, ProtectedError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from django.utils.translation import get_language
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
    CustomerForm, InvoiceItemFormSet, ApplyPaymentForm,
)
from .models import Invoice, Payment, Customer, Order

# ==========================
# DEFAULT_INVOICE_TERMS
# ==========================

# Default terms template for new invoices
DEFAULT_INVOICE_TERMS = (
    "• تُصدر هذه الفاتورة وفقًا لشروط مزون ألمنيوم.\n"
    "• يجب سداد المبلغ خلال 15 يومًا من تاريخ الفاتورة ما لم يُتفق على غير ذلك كتابيًا.\n"
    "• تحتفظ مزون ألمنيوم بحقها في إيقاف التوريد أو الخدمات في حال التأخر عن السداد.\n"
    "• في حال وجود أي ملاحظة على الفاتورة، يرجى التواصل خلال 3 أيام عمل من تاريخ الاستلام.\n"
)

# ==========================
# Helpers / Permissions
# ==========================

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


# ==========================
# Invoices
# ==========================

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
            # Pre-fill customer if passed in query params
            initial["customer"] = customer_id

        # Pre-fill default terms template for new invoices
        # Only on GET (not POST) and if no terms already provided
        if "terms" not in initial or not initial.get("terms"):
            initial["terms"] = DEFAULT_INVOICE_TERMS

        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        if self.request.POST:
            ctx["item_formset"] = InvoiceItemFormSet(self.request.POST)
        else:
            ctx["item_formset"] = InvoiceItemFormSet()

        # 👇 تجهيز بيانات المنتجات للـ JavaScript
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

        # أولاً: تأكد أن formset صحيح
        if not item_formset.is_valid():
            return self.form_invalid(form)

        # 1) نحفظ الفاتورة بدون إجمالي
        invoice = form.save(commit=False)
        # نحط رقم مبدئيًا صفر، بنحدثه بعد البنود
        invoice.total_amount = Decimal("0")
        # paid_amount يظل افتراضي (0) من الموديل
        invoice.save()  # هنا يتولد number تلقائياً من save() في الموديل
        self.object = invoice

        # 2) نحفظ البنود ونربطها بالفاتورة
        item_formset.instance = invoice
        item_formset.save()

        # 3) نحسب الإجمالي من البنود
        total = sum((item.subtotal for item in invoice.items.all()), Decimal("0"))
        invoice.total_amount = total
        invoice.save(update_fields=["total_amount"])

        # 4) رجوع للصفحة المطلوبة
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("accounting:invoice_list")




@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceUpdateView(UpdateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = "accounting/invoice_form.html"
    slug_field = "number"
    slug_url_kwarg = "number"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        invoice = self.object  # الفاتورة الحالية

        if self.request.POST:
            ctx["item_formset"] = InvoiceItemFormSet(self.request.POST, instance=invoice)
        else:
            ctx["item_formset"] = InvoiceItemFormSet(instance=invoice)

        # نفس JSON المنتجات المستخدم في الإنشاء
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

        # نحدّث بيانات الفاتورة نفسها أولاً
        invoice = form.save(commit=False)
        # نرجّع الإجمالي للصفر، ثم نحسبه من جديد بعد حفظ البنود
        invoice.total_amount = Decimal("0")
        invoice.save()
        self.object = invoice

        # نحفظ البنود (تعديل / حذف / إضافة)
        item_formset.instance = invoice
        item_formset.save()

        # نعيد حساب الإجمالي من البنود بعد التعديل
        total = sum((item.subtotal for item in invoice.items.all()), Decimal("0"))
        invoice.total_amount = total
        invoice.save(update_fields=["total_amount"])

        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        # بعد الحفظ يرجع لتفاصيل نفس الفاتورة
        return reverse("accounting:invoice_detail", kwargs={"number": self.object.number})



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
        initial.setdefault("date", timezone.now().date())
        return initial

    def form_valid(self, form):
        # ننشئ الـ Payment ونربطه بنفس العميل والفاتورة
        payment = form.save(commit=False)
        payment.customer = self.invoice.customer
        payment.invoice = self.invoice
        payment.save()  # هذا تلقائيًا يحدث paid_amount في save()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(
            "accounting:invoice_detail",
            kwargs={"number": self.invoice.number},
        )


@method_decorator(accounting_staff_required, name="dispatch")
class InvoicePrintView(DetailView):
    """
    صفحة طباعة للفاتورة (للموظف)
    """
    model = Invoice
    template_name = "accounting/invoice_print.html"
    context_object_name = "invoice"
    slug_field = "number"
    slug_url_kwarg = "number"


# ==========================
# Dashboard
# ==========================

@method_decorator(accounting_staff_required, name="dispatch")
class AccountingDashboardView(TemplateView):
    """
    لوحة مبسطة للمحاسبة:
    - إحصائيات عامة
    - آخر الفواتير
    - آخر الدفعات
    - آخر الطلبات
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

        return ctx


# ==========================
# Customers
# ==========================

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
            # بحث بالاسم أو اسم الشركة
            qs = qs.filter(
                Q(name__icontains=q) | Q(company_name__icontains=q)
            )
        return qs


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerCreateView(CreateView):
    model = Customer
    form_class = CustomerForm
    template_name = "accounting/customer_form.html"

    def get_success_url(self):
        return reverse("accounting:customer_list")


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerUpdateView(UpdateView):
    model = Customer
    form_class = CustomerForm
    template_name = "accounting/customer_form.html"

    def get_success_url(self):
        return reverse("accounting:customer_list")


@method_decorator(accounting_staff_required, name="dispatch")
class CustomerDeleteView(DeleteView):
    model = Customer
    template_name = "accounting/customer_confirm_delete.html"
    success_url = reverse_lazy("accounting:customer_list")

    def post(self, request, *args, **kwargs):
        """
        ننفّذ الحذف يدويًا عشان نقدر نمسك ProtectedError
        بدل ما نخليه يطلع 500.
        """
        self.object = self.get_object()
        try:
            # محاولة الحذف الفعلية
            self.object.delete()
        except ProtectedError:
            # هنا نجي لو عنده فواتير/دفعات/طلبات مرتبطة
            messages.error(
                request,
                "لا يمكن حذف هذا الزبون لأنه مرتبط بفواتير أو دفعات أو طلبات قائمة. "
                "يمكنك تعديل بياناته أو إبقاءه كما هو للسجلات المحاسبية."
            )
            return redirect("accounting:customer_detail", pk=self.object.pk)
        else:
            # لو الحذف نجح فعلاً
            messages.success(request, "تم حذف الزبون بنجاح.")
            return redirect(self.success_url)



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

        total_invoices = invoices.aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        total_paid = payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")

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
        return reverse("accounting:customer_detail", kwargs={"pk": self.customer.pk})


# ==========================
# Payment Recolonization
# ==========================
@accounting_staff_required
def apply_general_payment(request, pk):
    """
    تسوية دفعة عامة (بدون فاتورة) على فاتورة معيّنة.
    - لو المبلغ المسوّى = كامل الدفعة → نربط نفس الدفعة بالفاتورة.
    - لو المبلغ المسوّى < مبلغ الدفعة → ننشئ دفعة جديدة للفاتورة، وننقص المبلغ من الدفعة العامة.
    """
    # نسمح فقط بالدفعات العامة (invoice__isnull=True)
    payment = get_object_or_404(
        Payment,
        pk=pk,
        invoice__isnull=True,
    )
    customer = payment.customer

    # لو الزبون ما عنده ولا فاتورة، ما في شيء نعمله
    if not customer.invoices.exists():
        messages.error(request, "لا توجد فواتير لهذا الزبون لتسوية الدفعة عليها.")
        return redirect("accounting:customer_detail", pk=customer.pk)

    if request.method == "POST":
        form = ApplyPaymentForm(customer, payment.amount, request.POST)
        if form.is_valid():
            invoice = form.cleaned_data["invoice"]
            amount = form.cleaned_data["amount"]

            # الحالة 1: تسوية كاملة (المبلغ بالكامل)
            if amount == payment.amount:
                payment.invoice = invoice
                payment.save(update_fields=["invoice"])
                messages.success(
                    request,
                    f"تم تسوية الدفعة بالكامل على الفاتورة {invoice.number}.",
                )
            else:
                # الحالة 2: تسوية جزئية
                # إنشاء دفعة جديدة مرتبطة بالفاتورة
                Payment.objects.create(
                    customer=customer,
                    invoice=invoice,
                    amount=amount,
                    date=payment.date,
                    method=payment.method,
                    notes=f"تسوية جزء ({amount}) من الدفعة العامة #{payment.pk}",
                )
                # تقليل المبلغ المتبقي في الدفعة العامة
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




# ==========================
# Orders (function-based for staff)
# ==========================

@accounting_staff_required
def staff_order_list(request):
    orders = (
        Order.objects
        .select_related("customer", "confirmed_by")
        .prefetch_related("items__product")
        .order_by("-created_at", "id")
    )
    return render(
        request,
        "accounting/orders/staff_order_list.html",
        {"orders": orders},
    )


@accounting_staff_required
def staff_order_detail(request, pk):
    order = get_object_or_404(
        Order.objects
        .select_related("customer", "confirmed_by")
        .prefetch_related("items__product"),
        pk=pk,
    )
    return render(
        request,
        "accounting/orders/staff_order_detail.html",
        {"order": order},
    )


@accounting_staff_required
def staff_order_confirm(request, pk):
    order = get_object_or_404(Order, pk=pk)

    if request.method == "POST":
        if order.status != Order.STATUS_CONFIRMED:
            order.status = Order.STATUS_CONFIRMED
            order.confirmed_by = request.user
            order.confirmed_at = timezone.now()
            order.save(update_fields=["status", "confirmed_by", "confirmed_at"])
        return redirect("accounting:order_detail", pk=order.pk)

    # لو أحد فتح الرابط بـ GET نرجعه للتفاصيل
    return redirect("accounting:order_detail", pk=order.pk)


@accounting_staff_required
def staff_order_create(request):
    """
    إنشاء طلب موظف بسيط (زبون واحد + منتج واحد مبدئيًا).
    لاحقًا ممكن نربطه بـ StaffOrderForm لو حبّينا نعقّد المنطق.
    """
    if request.method == "POST":
        customer_id = request.POST.get("customer")
        product_id = request.POST.get("product")
        quantity = request.POST.get("quantity") or "1"
        notes = (request.POST.get("notes") or "").strip()

        customer = get_object_or_404(Customer, pk=customer_id)
        product = get_object_or_404(Product, pk=product_id)

        order = Order.objects.create(
            customer=customer,
            created_by=request.user,
            is_online=False,
            status=Order.STATUS_DRAFT,
            notes=notes,
        )
        order.items.create(
            product=product,
            quantity=quantity,
            unit_price=product.price,
        )

        # 🔹 رجوع لقائمة الطلبات مع كود اللغة (ar / en)
        lang = get_language() or "ar"
        return redirect(f"/{lang}/accounting/orders/")

    lang = get_language() or "ar"
    product_name_field = "name_ar" if lang.startswith("ar") else "name_en"

    customers = Customer.objects.all().order_by("name")
    products = Product.objects.filter(is_active=True).order_by(product_name_field)

    return render(
        request,
        "accounting/orders/staff_order_create.html",
        {
            "customers": customers,
            "products": products,
        },
    )
