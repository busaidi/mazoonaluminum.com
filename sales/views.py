# sales/views.py
import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext_lazy as _
from django.views import generic

from inventory.models import Product
from .forms import (
    SalesDocumentForm,
    SalesLineFormSet,
    DeliveryNoteForm,
    DeliveryLineFormSet
)
from .models import SalesDocument, DeliveryNote


# ===================================================================
# 1. قائمة المبيعات (List Views)
# ===================================================================

class QuotationListView(LoginRequiredMixin, generic.ListView):
    model = SalesDocument
    template_name = "sales/quotation_list.html"
    context_object_name = "documents"
    paginate_by = 20

    def get_queryset(self):
        queryset = SalesDocument.objects.quotations().select_related("contact")

        # استلام كلمة البحث
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.search(q)

        # استلام فلتر الحالة (اختياري)
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        return queryset.order_by("-date", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # نمرر القيم الحالية للقالب لكي تبقى في مربع البحث
        context['current_q'] = self.request.GET.get('q', '')
        context['current_status'] = self.request.GET.get('status', '')
        # نمرر خيارات الحالة للقائمة المنسدلة
        context['status_choices'] = SalesDocument.Status.choices
        return context


class OrderListView(LoginRequiredMixin, generic.ListView):
    model = SalesDocument
    template_name = "sales/order_list.html"
    context_object_name = "documents"
    paginate_by = 20

    def get_queryset(self):
        queryset = SalesDocument.objects.orders().select_related("contact")

        q = self.request.GET.get('q')
        if q:
            queryset = queryset.search(q)

        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        return queryset.order_by("-date", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_q'] = self.request.GET.get('q', '')
        context['current_status'] = self.request.GET.get('status', '')
        context['status_choices'] = SalesDocument.Status.choices
        return context


# ===================================================================
# 2. إنشاء وتعديل المبيعات (Create & Update)
# ===================================================================

class SalesDocumentMixin:
    """
    Mixin يحتوي على المنطق المشترك بين الإنشاء والتعديل
    للتعامل مع FormSet (البنود) والتحقق من صحتها.
    """
    model = SalesDocument
    form_class = SalesDocumentForm
    template_name = "sales/sales_form.html"

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)

        # 1. جلب المنتجات
        products = Product.objects.filter(is_active=True).select_related('base_uom', 'alt_uom')

        # 2. بناء القاموس (Dictionary)
        products_dict = {}
        for p in products:
            # المفتاح يجب أن يكون نصاً ليطابق ما يأتي من HTML
            products_dict[str(p.id)] = {
                "name": p.name,
                "price": float(p.default_sale_price) if p.default_sale_price else 0.0,
                "base_uom_id": p.base_uom_id,
                "base_uom_name": p.base_uom.name if p.base_uom else "",
                "alt_uom_id": p.alt_uom_id if p.alt_uom_id else None,
                "alt_uom_name": p.alt_uom.name if p.alt_uom else "",
                "alt_factor": float(p.alt_factor) if p.alt_factor else 1.0,
            }

        # ==========================================================
        # التعديل هنا: نرسل القاموس products_dict كما هو (بدون json.dumps)
        # ==========================================================
        data["products_dict"] = products_dict

        # 4. إعداد FormSet
        if self.request.POST:
            data["lines"] = SalesLineFormSet(self.request.POST, instance=self.object)
        else:
            data["lines"] = SalesLineFormSet(instance=self.object)

        return data

    def form_valid(self, form):
        """
        يتم استدعاء هذه الدالة عند صحة النموذج الرئيسي (Header).
        هنا يجب التحقق من صحة البنود (Lines) وحفظ الكل داخل Transaction.
        """
        context = self.get_context_data()
        lines = context["lines"]

        # ملاحظة: context['lines'] هنا قد تكون نسخة جديدة غير مرتبطة بـ POST إذا لم نكن حذرين
        # لكن لأننا استدعينا get_context_data داخل form_valid، ستقوم بإعادة إنشاء الـ FormSet
        # بناءً على self.request.POST (انظر الشرط في الدالة أعلاه).

        if lines.is_valid():
            with transaction.atomic():
                # 1. حفظ المستند الرئيسي وتعيين المستخدم
                self.object = form.save(commit=False)
                if not self.object.created_by:
                    self.object.created_by = self.request.user
                self.object.updated_by = self.request.user

                # تعيين نوع المستند بناءً على الـ View الحالية
                if not self.object.pk:  # إذا كان جديداً
                    self.object.kind = self.get_initial_kind()

                self.object.save()

                # 2. حفظ البنود وربطها بالمستند
                lines.instance = self.object
                lines.save()

                # 3. إعادة حساب الإجماليات
                self.object.recompute_totals()

            messages.success(self.request, _("تم حفظ المستند بنجاح."))
            return super().form_valid(form)
        else:
            # إذا كانت البنود غير صحيحة، نعيد عرض الصفحة مع الأخطاء
            return self.render_to_response(self.get_context_data(form=form))

    def get_initial_kind(self):
        """
        دالة افتراضية، يتم تجاوزها في الـ Views الفرعية
        لتحديد هل ننشئ عرض سعر أم أمر بيع.
        """
        return SalesDocument.Kind.QUOTATION


class QuotationCreateView(LoginRequiredMixin, SalesDocumentMixin, generic.CreateView):
    """إنشاء عرض سعر جديد"""

    def get_initial_kind(self):
        return SalesDocument.Kind.QUOTATION

    def get_success_url(self):
        return reverse("sales:quotation_list")


class OrderCreateView(LoginRequiredMixin, SalesDocumentMixin, generic.CreateView):
    """إنشاء أمر بيع جديد مباشرة"""

    def get_initial_kind(self):
        return SalesDocument.Kind.ORDER

    def get_success_url(self):
        return reverse("sales:order_list")


class SalesDocumentUpdateView(LoginRequiredMixin, SalesDocumentMixin, generic.UpdateView):
    """
    تعديل مستند موجود (سواء كان عرض سعر أو أمر بيع).
    """

    def get_success_url(self):
        # توجيه المستخدم للقائمة المناسبة حسب نوع المستند
        if self.object.kind == SalesDocument.Kind.ORDER:
            return reverse("sales:order_list")
        return reverse("sales:quotation_list")


# ===================================================================
# 3. عرض التفاصيل (Detail View)
# ===================================================================

class SalesDocumentDetailView(LoginRequiredMixin, generic.DetailView):
    """
    عرض تفاصيل المستند (للطباعة أو للمراجعة).
    """
    model = SalesDocument
    template_name = "sales/sales_detail.html"
    context_object_name = "document"

    def get_queryset(self):
        # تحسين الأداء بجلب البيانات المرتبطة مرة واحدة
        return super().get_queryset().select_related("contact").prefetch_related("lines__product")


# ===================================================================
# 4. إجراءات (Actions) - تحويل وحذف
# ===================================================================

@transaction.atomic
def convert_quotation_to_order(request, pk):
    """
    تحويل عرض السعر إلى أمر بيع.
    """
    document = get_object_or_404(SalesDocument, pk=pk)

    # التحقق من الصلاحية (Logic موجود في الموديل)
    if not document.can_be_converted_to_order():
        messages.error(request, _("لا يمكن تحويل هذا المستند (قد يكون ملغياً أو هو بالفعل أمر بيع)."))
        return redirect("sales:quotation_list")

    # التحديث
    document.kind = SalesDocument.Kind.ORDER
    document.save(update_fields=["kind", "updated_at"])

    messages.success(request, _("تم تحويل عرض السعر إلى أمر بيع بنجاح."))
    return redirect("sales:order_list")


@transaction.atomic
def confirm_document(request, pk):
    """
    تأكيد المستند (نقل الحالة من Draft إلى Confirmed).
    """
    document = get_object_or_404(SalesDocument, pk=pk)

    if document.status != SalesDocument.Status.DRAFT:
        messages.warning(request, _("المستند ليس في حالة مسودة ليتم تأكيده."))
    else:
        document.status = SalesDocument.Status.CONFIRMED
        document.save(update_fields=["status", "updated_at"])
        messages.success(request, _("تم تأكيد المستند."))

    return redirect("sales:document_detail", pk=pk)


def delete_document(request, pk):
    """
    حذف ناعم (Soft Delete) للمستند.
    """
    document = get_object_or_404(SalesDocument, pk=pk)

    # نستخدم دالة soft_delete التي كتبناها في BaseModel
    document.soft_delete(user=request.user)

    messages.success(request, _("تم حذف المستند."))

    if document.kind == SalesDocument.Kind.ORDER:
        return redirect("sales:order_list")
    return redirect("sales:quotation_list")


# ===================================================================
# 5. Delivery Note Views (مختصرة وسريعة)
# ===================================================================

class DeliveryNoteCreateView(LoginRequiredMixin, generic.CreateView):
    model = DeliveryNote
    form_class = DeliveryNoteForm
    template_name = "sales/delivery_form.html"

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)

        # 1. تجهيز بيانات المنتجات للجافا سكريبت (UOM Filtering)
        products = Product.objects.filter(is_active=True).select_related('base_uom', 'alt_uom')
        products_dict = {}
        for p in products:
            products_dict[str(p.id)] = {
                "base_uom_id": p.base_uom_id,
                "base_uom_name": p.base_uom.name if p.base_uom else "",
                "alt_uom_id": p.alt_uom_id if p.alt_uom_id else None,
                "alt_uom_name": p.alt_uom.name if p.alt_uom else "",
                # لا نحتاج السعر في مذكرة التسليم
            }
        data["products_dict"] = products_dict

        # 2. FormSet
        if self.request.POST:
            data["lines"] = DeliveryLineFormSet(self.request.POST)
        else:
            data["lines"] = DeliveryLineFormSet()

        return data

    def form_valid(self, form):
        context = self.get_context_data()
        lines = context["lines"]

        if lines.is_valid():
            with transaction.atomic():
                self.object = form.save(commit=False)
                self.object.created_by = self.request.user
                self.object.save()
                lines.instance = self.object
                lines.save()
            # سنقوم بالتوجيه للقائمة (سأنشئها لك لاحقاً) أو للمبيعات مؤقتاً
            return redirect("sales:order_list")

        return self.render_to_response(self.get_context_data(form=form))





class DeliveryListView(LoginRequiredMixin, generic.ListView):
    """
    عرض قائمة مذكرات التسليم.
    """
    model = DeliveryNote
    template_name = "sales/delivery_list.html"
    context_object_name = "deliveries"
    paginate_by = 20

    def get_queryset(self):
        # نستخدم select_related لجلب بيانات العميل وأمر البيع لتقليل الاستعلامات
        # return DeliveryNote.objects.alive().select_related("contact", "order").order_by("-date", "-id")
        return DeliveryNote.objects.all().select_related("contact", "order").order_by("-date", "-id")


class DeliveryDetailView(LoginRequiredMixin, generic.DetailView):
    """
    عرض تفاصيل مذكرة التسليم (مثل بوليصة الشحن - Packing Slip).
    عادة لا تظهر الأسعار هنا، فقط الكميات.
    """
    model = DeliveryNote
    template_name = "sales/delivery_detail.html"
    context_object_name = "delivery"

    def get_queryset(self):
        return super().get_queryset().select_related("contact", "order").prefetch_related("lines__product")


# ولا تنسَ إضافة هذه الدوال للإجراءات (Actions) الخاصة بالتسليم
@transaction.atomic
def confirm_delivery(request, pk):
    delivery = get_object_or_404(DeliveryNote, pk=pk)
    if delivery.status == DeliveryNote.Status.DRAFT:
        delivery.status = DeliveryNote.Status.CONFIRMED
        delivery.save()
        messages.success(request, _("تم تأكيد التسليم، وتم خصم الكميات من المخزون (نظرياً)."))
        # ملاحظة: هنا يجب استدعاء دالة خصم المخزون الحقيقية لاحقاً
    return redirect("sales:delivery_detail", pk=pk)

def delete_delivery(request, pk):
    delivery = get_object_or_404(DeliveryNote, pk=pk)
    delivery.soft_delete(user=request.user)
    messages.success(request, _("تم حذف مذكرة التسليم."))
    return redirect("sales:delivery_list")


# sales/views.py (أضف هذا في البداية أو النهاية)

from django.db.models import Sum


class SalesDashboardView(LoginRequiredMixin, generic.TemplateView):
    template_name = "sales/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # إحصائيات بسيطة
        context['draft_quotations_count'] = SalesDocument.objects.quotations().drafts().count()
        context[
            'current_month_orders_count'] = SalesDocument.objects.orders().confirmed().count()  # يمكن إضافة فلتر التاريخ لاحقاً

        # أوامر لم يتم تسليمها بالكامل (مثال مبسط: نعتبر كل المسودة في التسليم معلقة)
        context['pending_deliveries_count'] = DeliveryNote.objects.drafts().count()

        # الإجمالي (يحتاج لمنطق أدق للعملات، هنا نجمع الأرقام فقط كمثال)
        total = SalesDocument.objects.orders().confirmed().aggregate(t=Sum('total_amount'))['t']
        context['total_revenue'] = total if total else 0

        return context