# core/views/attachments.py
from __future__ import annotations

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View

from core.models import Attachment
from core.forms import AttachmentForm


class AttachmentParentMixin:
    """
    Mixin عام للتعامل مع الكيان الأب (فاتورة، أمر، ...).
    يوفّر:
      - get_attachment_parent_object()
      - get_attachment_success_url()
    """

    # يجب ضبطها في الكلاس الابن:
    attachment_parent_model = None  # مثال: Invoice
    attachment_parent_lookup_url_kwarg = "pk"     # إسم الـ kwarg في الـ URL (مثال: "number")
    attachment_parent_lookup_field = "pk"        # الحقل في الموديل (مثال: "number")
    attachment_success_url_name = None           # مثال: "accounting:invoice_detail"

    def get_attachment_parent_model(self):
        if self.attachment_parent_model is None:
            raise ImproperlyConfigured("attachment_parent_model must be set.")
        return self.attachment_parent_model

    def get_attachment_parent_lookup_value(self):
        kwarg_name = self.attachment_parent_lookup_url_kwarg
        try:
            return self.kwargs[kwarg_name]
        except KeyError:
            raise ImproperlyConfigured(
                f"URL kwarg '{kwarg_name}' not found in view kwargs."
            )

    def get_attachment_parent_object(self):
        model = self.get_attachment_parent_model()
        lookup_value = self.get_attachment_parent_lookup_value()
        field_name = self.attachment_parent_lookup_field
        return get_object_or_404(model, **{field_name: lookup_value})

    # --------- redirect بعد الإضافة/الحذف ---------
    def get_attachment_success_url_kwargs(self, parent):
        """
        بشكل افتراضي نفترض أن الـ URL يستخدم نفس الـ kwarg والـ field.
        يمكن للكلاس الابن أن يغيّر هذا إذا احتاج.
        """
        field_name = self.attachment_parent_lookup_field
        url_kwarg = self.attachment_parent_lookup_url_kwarg
        return {url_kwarg: getattr(parent, field_name)}

    def get_attachment_success_url(self, parent):
        if self.attachment_success_url_name is None:
            raise ImproperlyConfigured("attachment_success_url_name must be set.")
        return reverse(
            self.attachment_success_url_name,
            kwargs=self.get_attachment_success_url_kwargs(parent),
        )


class BaseAttachmentCreateView(AttachmentParentMixin, View):
    """
    فيو عام لرفع مرفق لأي كيان (فاتورة، أمر، ...).
    يعتمد على:
      - AttachmentForm
      - Attachment (GenericForeignKey)
    """

    form_class = AttachmentForm
    success_message = _("تم رفع المرفق بنجاح.")
    error_message = _("تعذر حفظ المرفق، يرجى مراجعة البيانات.")

    def post(self, request, *args, **kwargs):
        parent = self.get_attachment_parent_object()
        form = self.form_class(request.POST, request.FILES)

        if form.is_valid():
            attachment: Attachment = form.save(commit=False)
            attachment.content_object = parent
            if request.user.is_authenticated:
                attachment.uploaded_by = request.user
            attachment.save()
            messages.success(request, self.success_message)
        else:
            messages.error(request, self.error_message)

        return redirect(self.get_attachment_success_url(parent))


class BaseAttachmentDeleteView(AttachmentParentMixin, View):
    """
    فيو عام لتعطيل (حذف منطقي) مرفق تابع لكيان معيّن.
    """

    attachment_model = Attachment
    success_message = _("تم حذف المرفق.")
    permission_denied_message = _("ليست لديك صلاحية لحذف هذا المرفق.")

    def get_attachment_queryset(self, parent):
        """
        جلب المرفقات المرتبطة بالكيان الأب فقط (لأمان إضافي).
        """
        ct = ContentType.objects.get_for_model(parent)
        return self.attachment_model.objects.filter(
            content_type=ct,
            object_id=parent.pk,
            is_active=True,
        )

    def has_delete_permission(self, request, attachment):
        """
        صلاحيات حذف:
          - مستخدم staff
          - أو نفس المستخدم الذي رفع المرفق
        """
        if not request.user.is_authenticated:
            return False
        return request.user.is_staff or attachment.uploaded_by == request.user

    def post(self, request, *args, **kwargs):
        parent = self.get_attachment_parent_object()
        qs = self.get_attachment_queryset(parent)
        attachment = get_object_or_404(qs, pk=self.kwargs["pk"])

        if self.has_delete_permission(request, attachment):
            attachment.is_active = False
            attachment.save(update_fields=["is_active"])
            messages.success(request, self.success_message)
        else:
            messages.error(request, self.permission_denied_message)

        return redirect(self.get_attachment_success_url(parent))
