# core/views/attachments.py
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views import View

from core.models import Attachment
from core.forms import AttachmentForm


def _get_next_url(request):
    """
    نحاول نرجع لنفس صفحة التفاصيل:
    - أولاً من حقل hidden اسمه "next"
    - إذا ما فيه، نستخدم HTTP_REFERER
    - إذا ما فيه، نرجع للـ "/"
    """
    return (
        request.POST.get("next")
        or request.GET.get("next")
        or request.META.get("HTTP_REFERER")
        or "/"
    )


@method_decorator(login_required, name="dispatch")
class AttachmentCreateView(View):
    """
    فيو عام لرفع مرفق لأي كيان.
    لا يحتاج URL مخصص لكل موديل.

    يتوقع في POST:
      - file, title, description (من AttachmentForm)
      - content_type (id)
      - object_id
      - next (اختياري) → نرجع له بعد الحفظ
    """

    form_class = AttachmentForm

    def post(self, request, *args, **kwargs):
        next_url = _get_next_url(request)

        content_type_id = request.POST.get("content_type")
        object_id = request.POST.get("object_id")

        if not content_type_id or not object_id:
            messages.error(request, _("تعذر تحديد العنصر المرتبط بالمرفق."))
            return redirect(next_url)

        try:
            ct = ContentType.objects.get(pk=content_type_id)
        except ContentType.DoesNotExist:
            messages.error(request, _("نوع الكيان غير معروف."))
            return redirect(next_url)

        parent = get_object_or_404(ct.model_class(), pk=object_id)

        form = self.form_class(request.POST, request.FILES)
        if form.is_valid():
            attachment: Attachment = form.save(commit=False)
            attachment.content_object = parent
            if request.user.is_authenticated:
                attachment.uploaded_by = request.user
            attachment.save()
            messages.success(request, _("تم رفع المرفق بنجاح."))
        else:
            messages.error(request, _("تعذر حفظ المرفق، يرجى مراجعة البيانات."))

        return redirect(next_url)


@method_decorator(login_required, name="dispatch")
class AttachmentDeleteView(View):
    """
    فيو عام لحذف (تعطيل) مرفق.
    لا يحتاج معرفة نوع الموديل.
    """

    def post(self, request, pk, *args, **kwargs):
        next_url = _get_next_url(request)

        attachment = get_object_or_404(Attachment, pk=pk, is_active=True)

        # صلاحيات بسيطة:
        # - staff
        # - أو نفس المستخدم الذي رفع المرفق
        if not request.user.is_staff and attachment.uploaded_by != request.user:
            messages.error(request, _("ليست لديك صلاحية لحذف هذا المرفق."))
            return redirect(next_url)

        attachment.is_active = False
        attachment.save(update_fields=["is_active"])
        messages.success(request, _("تم حذف المرفق."))

        return redirect(next_url)


# -------------------------------------------------------------------
# Mixin لحقن سياق المرفقات في أي DetailView
# -------------------------------------------------------------------
class AttachmentPanelMixin:
    """
    يُستخدم مع DetailView (أو أي View فيه self.object) ليضيف إلى context:
      - attachments
      - attachments_count
      - attachment_form
      - attachment_content_type_id
      - attachment_object_id
      - attachment_next_url

    الهدف: تضمين panel واحد فقط في القالب:
      {% include "core/attachments/_panel.html" %}
    """

    def get_attachment_parent_for_panel(self):
        """
        الافتراضي: self.object (في DetailView)
        يمكن override إذا احتجت.
        """
        obj = getattr(self, "object", None)
        if obj is None and hasattr(self, "get_object"):
            obj = self.get_object()
        return obj

    def inject_attachment_panel_context(self, context):
        from django.contrib.contenttypes.models import ContentType

        parent = self.get_attachment_parent_for_panel()
        if parent is None:
            return context

        ct = ContentType.objects.get_for_model(parent)

        attachments = (
            Attachment.objects
            .filter(content_type=ct, object_id=parent.pk, is_active=True)
            .select_related("uploaded_by")
            .order_by("-uploaded_at")
        )

        # نضيف delete_url الجاهز لكل مرفق
        for att in attachments:
            att.delete_url = reverse("core:attachment_delete", args=[att.pk])

        request = getattr(self, "request", None)
        next_url = request.get_full_path() if request else "/"

        context["attachments"] = attachments
        context["attachments_count"] = attachments.count()
        context["attachment_form"] = AttachmentForm()
        context["attachment_content_type_id"] = ct.pk
        context["attachment_object_id"] = parent.pk
        context["attachment_next_url"] = next_url
        return context
