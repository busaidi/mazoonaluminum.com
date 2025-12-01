# core/mixins.py

from django.views.generic.edit import ModelFormMixin
from django.views import View
from django.shortcuts import get_object_or_404, redirect
from django.core.exceptions import ImproperlyConfigured


class UserStampedMixin(ModelFormMixin):
    """
    مكسين بسيط لتعبئة created_by و updated_by تلقائيًا.

    متى يستخدم؟
    - مع أي View يعتمد على ModelForm (CreateView / UpdateView / FormView مع ModelForm).

    آلية العمل:
    - قبل حفظ الفورم، يضيف:
      - created_by = request.user إذا كان إنشاء أول مرة.
      - updated_by = request.user في كل مرة يتم فيها حفظ النموذج.
    - لا يتدخل في الفالديشن ولا في الـ redirect.
    """

    def form_valid(self, form):
        user = getattr(self.request, "user", None)

        # نتعامل مع الـ instance على مستوى الفورم
        instance = form.instance

        # لو المستخدم مسجّل دخول
        if user and user.is_authenticated:
            # أول مرة ينشأ فيها السجل (ما له pk)
            if not instance.pk and hasattr(instance, "created_by"):
                instance.created_by = user

            # في كل حفظ (إنشاء أو تعديل)
            if hasattr(instance, "updated_by"):
                instance.updated_by = user

        # نترك الحفظ الفعلي لـ ModelFormMixin (CreateView/UpdateView)
        return super().form_valid(form)





class SoftDeleteMixin(View):
    """
    مكسين لتنفيذ soft delete بدلاً من الحذف الفعلي.

    الاستخدام:
    - استعمله مع View مخصص للحذف (POST فقط).
    - يتوقّع أن الموديل يرث من BaseModel وفيه دالة soft_delete(user=None).

    المتطلبات:
    - تعريف:
        model = YourModel
        success_url = reverse_lazy("...")
    """

    model = None           # يجب تعيينه في الـ View
    pk_url_kwarg = "pk"    # اسم البراميتر في ال URL
    success_url = None     # يجب تعيينه أو override get_success_url()

    def get_object(self):
        if self.model is None:
            raise ImproperlyConfigured("SoftDeleteMixin requires 'model' attribute.")
        pk = self.kwargs.get(self.pk_url_kwarg)
        return get_object_or_404(self.model, pk=pk)

    def get_success_url(self):
        if self.success_url is None:
            raise ImproperlyConfigured(
                "SoftDeleteMixin requires 'success_url' or override get_success_url()."
            )
        return self.success_url

    def post(self, request, *args, **kwargs):
        obj = self.get_object()

        # نتأكد أن فيه دالة soft_delete
        if not hasattr(obj, "soft_delete"):
            raise ImproperlyConfigured(
                f"{self.model.__name__} does not implement soft_delete()."
            )

        user = request.user if request.user.is_authenticated else None
        obj.soft_delete(user=user)

        return redirect(self.get_success_url())