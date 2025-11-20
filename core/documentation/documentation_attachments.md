# Documentation – Attachments Module (`core`)

هذا الملف يشرح نظام **المرفقات (Attachments)** في مشروعك `mazoonaluminum.com`، ويغطي:

- موديل المرفقات: `core/models/attachments.py`
- الفيوهات: `core/views/attachments.py`
- الـ Mixin الخاص بالـ panel
- مسارات الـ URLs
- قالب الـ panel الجاهز: `templates/core/attachments/_panel.html`
- طريقة الاستخدام مع أي DetailView (فاتورة، أوردر، عميل، ...)

> الهدف: يكون عندك نظام مرفقات عام تقدر تركّبه على أي موديل في المشروع بدون تكرار كود.

---

## 1. موديل المرفقات `core/models/attachments.py`

### 1.1 دالة مسار الرفع `attachment_upload_to`

```python
def attachment_upload_to(instance: "Attachment", filename: str) -> str:
    """
    مسار رفع المرفقات داخل media/.
    مثال:
        attachments/accounting/invoice/123/filename.pdf
    """
    if instance.content_type:
        app_label = instance.content_type.app_label
        model_name = instance.content_type.model  # lowercase model name
    else:
        app_label = "unknown"
        model_name = "unknown"

    return os.path.join(
        "attachments",
        app_label,
        model_name,
        str(instance.object_id or "unassigned"),
        filename,
    )
```

**الفكرة:**

- هذه الدالة تُستخدم في `FileField(upload_to=...)` لتحديد مسار حفظ الملفات داخل `MEDIA_ROOT`.
- تقرأ من `instance.content_type`:
  - `app_label` → اسم التطبيق (مثلًا: `accounting`).
  - `model_name` → اسم الموديل بالـ lowercase (مثلًا: `invoice`).
- تستخدم `instance.object_id` لإنشاء مجلد خاص بكل كائن (مثلًا: فاتورة رقم 123).

**مثال لمسار نهائي:**

```text
media/
  attachments/
    accounting/
      invoice/
        123/
          contract.pdf
          design.png
```

إذا لم يكن هناك `content_type` لأي سبب، تستخدم `unknown/unknown/...`.

---

### 1.2 موديل `Attachment`

```python
class Attachment(models.Model):
    """
    مرفق عام يمكن ربطه بأي موديل في النظام (فاتورة، أمر، عميل، مشروع، ...).
    """
```

#### 1.2.1 الربط العام بأي موديل (Generic relation)

```python
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name=_("نوع الكيان"),
    )
    object_id = models.PositiveIntegerField(
        verbose_name=_("معرّف الكيان"),
    )
    content_object = GenericForeignKey("content_type", "object_id")
```

- `content_type`:
  - يشير إلى جدول `django_content_type`، الذي يعرّف الموديل (app + model).
- `object_id`:
  - يحتوي رقم الـ PK للكائن المرتبط (مثلًا: `invoice.id`).
- `content_object`:
  - هو `GenericForeignKey`، يسمح لك بـ:
    - قراءة الكائن المرتبط مباشرة: `attachment.content_object` يعيد (Invoice, Order, Customer, ...).
    - يملأ تلقائياً حقلي `content_type` و `object_id` عندما تعيّن `content_object`.

> بهذه الطريقة، **نستخدم جدول واحد للمرفقات** لأي موديل بدل ما نعمل FK منفصل لكل واحد.

---

#### 1.2.2 بيانات الملف

```python
    file = models.FileField(
        upload_to=attachment_upload_to,
        verbose_name=_("الملف"),
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("عنوان المرفق"),
        help_text=_("اسم داخلي يساعدك على تمييز المرفق."),
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("وصف"),
        help_text=_("ملاحظات إضافية حول المرفق (اختياري)."),
    )
```

- `file`: الملف نفسه (PDF, صورة, ZIP, ...)، يُخزن في المسار الذي تبنيه `attachment_upload_to`.
- `title`: عنوان وصفي داخلي (مثلًا: "عقد الزبون" أو "التصميم النهائي").
- `description`: ملاحظات إضافية (اختيارية).

---

#### 1.2.3 معلومات الرفع وحالة المرفق

```python
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_attachments",
        verbose_name=_("تم الرفع بواسطة"),
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("تاريخ الرفع"),
    )

    is_public = models.BooleanField(
        default=True,
        verbose_name=_("مرئي للواجهة؟"),
        help_text=_("يمكن استخدامه لاحقًا لفلترة المرفقات في البورتال/الويب."),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("مفعّل"),
        help_text=_("بدلاً من الحذف النهائي، يمكنك إلغاء التفعيل لإخفاء المرفق."),
    )
```

- `uploaded_by`:
  - المستخدم الذي رفع المرفق (staff أو portal user).
- `uploaded_at`:
  - تاريخ ووقت إنشاء السجل.
- `is_public`:
  - مستقبلاً تقدر تستخدمه للتمييز بين مرفقات داخلية ومرفقات تظهر للزبون في البورتال.
- `is_active`:
  - "حذف منطقي" (Soft delete):
    - بدل `delete()`، نغيره إلى `False` حتى يختفي من الواجهة مع إمكانية الاحتفاظ بالسجل في الـ DB.

---

#### 1.2.4 الإعدادات الإضافية و `__str__`

```python
    class Meta:
        verbose_name = _("مرفق")
        verbose_name_plural = _("المرفقات")
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["uploaded_at"]),
            models.Index(fields=["is_active"]),
        ]
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        if self.title:
            return self.title
        return os.path.basename(self.file.name or "") or f"Attachment #{self.pk}
```

- `indexes`:
  - لتحسين الاستعلام عن المرفقات:
    - حسب `content_type + object_id` (أهم واحد).
    - حسب تاريخ الرفع.
    - حسب الحالة `is_active`.
- `ordering`:
  - ترتيب المرفقات افتراضيًا من الأحدث إلى الأقدم.
- `__str__`:
  - يعرض عنوان المرفق إن وُجد.
  - أو اسم الملف.
  - أو fallback باسم مثل: `Attachment #12`.

---

## 2. الفيوهات `core/views/attachments.py`

### 2.1 الدالة `_get_next_url`

```python
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
```

**الهدف:**  
تحديد الرابط الذي سيتم redirect إليه بعد إضافة أو حذف مرفق، بالأولوية التالية:

1. قيمة `next` في `POST` (hidden input في الفورم).
2. لو غير موجود → قيمة `next` في `GET`.
3. لو غير موجود → قيمة `HTTP_REFERER` من الـ headers (الرابط السابق).
4. لو كل ذلك غير متوفر → يرجع `/` كقيمة افتراضية.

---

### 2.2 فيو إنشاء المرفقات `AttachmentCreateView`

```python
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
```

- الفيو عام (generic) لرفع مرفق لأي موديل.
- محمي بـ `login_required` → لا يمكن رفع مرفقات بدون تسجيل الدخول.
- يعتمد على `AttachmentForm` (موديل فورم بسيط على `Attachment`).

#### منطق الـ POST

```python
    def post(self, request, *args, **kwargs):
        next_url = _get_next_url(request)

        content_type_id = request.POST.get("content_type")
        object_id = request.POST.get("object_id")

        if not content_type_id or not object_id:
            messages.error(request, _("تعذر تحديد العنصر المرتبط بالمرفق."))
            return redirect(next_url)
```

- يقرأ `content_type` و `object_id` من الـ POST (مُمررة من القالب).
- لو أحدهما غير موجود → رسالة خطأ + redirect للـ `next_url`.

```python
        try:
            ct = ContentType.objects.get(pk=content_type_id)
        except ContentType.DoesNotExist:
            messages.error(request, _("نوع الكيان غير معروف."))
            return redirect(next_url)

        parent = get_object_or_404(ct.model_class(), pk=object_id)
```

- يتأكد أن نوع المحتوى (ContentType) موجود.
- يجلب الكائن الأب (مثلًا: Invoice، Order، Customer) عبر `get_object_or_404`.

```python
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
```

- ينشئ نموذج المرفق من البيانات والملف المرفوع.
- `commit=False`:
  - حتى نتمكن من تعيين `attachment.content_object` أولًا،
  - هذا يملأ `content_type` و `object_id` تلقائيًا.
- يعيّن `uploaded_by = request.user` إن كان المستخدم مسجلاً.
- يحفظ السجل، ثم:
  - عند النجاح → رسالة نجاح.
  - عند الفشل → رسالة خطأ عامة.
- في النهاية يرجع (redirect) إلى `next_url` (عادةً صفحة التفاصيل).

> **مهم:** أنت لا تستدعي هذا الفيو يدويًا؛ فقط توجه الـ form في القالب إلى:  
> `{% url 'core:attachment_add' %}` والفيو يتكفل بالباقي.

---

### 2.3 فيو حذف المرفقات `AttachmentDeleteView`

```python
@method_decorator(login_required, name="dispatch")
class AttachmentDeleteView(View):
    """
    فيو عام لحذف (تعطيل) مرفق.
    لا يحتاج معرفة نوع الموديل.
    """

    def post(self, request, pk, *args, **kwargs):
        next_url = _get_next_url(request)

        attachment = get_object_or_404(Attachment, pk=pk, is_active=True)
```

- يستقبل `pk` للمرفق من الـ URL.
- لا يتعامل إلا مع مرفقات `is_active=True` (حتى لا يعيد تعطيل نفس المرفق).

#### صلاحيات الحذف

```python
        # صلاحيات بسيطة:
        # - staff
        # - أو نفس المستخدم الذي رفع المرفق
        if not request.user.is_staff and attachment.uploaded_by != request.user:
            messages.error(request, _("ليست لديك صلاحية لحذف هذا المرفق."))
            return redirect(next_url)
```

- يسمح بالحذف في الحالات التالية:
  - المستخدم `is_staff`، أو
  - نفس المستخدم الذي رفع المرفق.

#### الحذف المنطقي

```python
        attachment.is_active = False
        attachment.save(update_fields=["is_active"])
        messages.success(request, _("تم حذف المرفق."))

        return redirect(next_url)
```

- يغيّر `is_active` إلى `False` (Soft delete).
- يظهر رسالة نجاح.
- يرجع إلى `next_url` (غالبًا صفحة التفاصيل).

---

## 3. الـ Mixin: `AttachmentPanelMixin`

هذا الـ mixin هو ما يربط بين الفيو (DetailView) والقالب `_panel.html`، ويحقن بيانات المرفقات في الـ context.

```python
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
```

### 3.1 تحديد الكائن الأب `get_attachment_parent_for_panel`

```python
    def get_attachment_parent_for_panel(self):
        """
        الافتراضي: self.object (في DetailView)
        يمكن override إذا احتجت.
        """
        obj = getattr(self, "object", None)
        if obj is None and hasattr(self, "get_object"):
            obj = self.get_object()
        return obj
```

- بشكل افتراضي، الكائن الأب هو `self.object` في الـ `DetailView`.
- لو `self.object` غير موجود بعد، يحاول استدعاء `self.get_object()`.
- يمكنك عمل override لهذه الدالة:
  - لو أردت ربط المرفقات بكائن مختلف عن `self.object`.

---

### 3.2 حقن بيانات المرفقات في الـ context

```python
    def inject_attachment_panel_context(self, context):
        from django.contrib.contenttypes.models import ContentType

        parent = self.get_attachment_parent_for_panel()
        if parent is None:
            return context

        ct = ContentType.objects.get_for_model(parent)
```

- يجلب الكائن الأب (فاتورة، أوردر، ...).
- يستخرج الـ ContentType الخاص به باستخدام `get_for_model(parent)`.

```python
        attachments = (
            Attachment.objects
            .filter(content_type=ct, object_id=parent.pk, is_active=True)
            .select_related("uploaded_by")
            .order_by("-uploaded_at")
        )
```

- يسترجع قائمة المرفقات المرتبطة:
  - بنفس `content_type`.
  - بنفس `object_id` (هو `parent.pk`).
  - والتي ما زالت `is_active=True`.
- مع `select_related("uploaded_by")` لتقليل عدد الاستعلامات.

```python
        # نضيف delete_url الجاهز لكل مرفق
        for att in attachments:
            att.delete_url = reverse("core:attachment_delete", args=[att.pk])
```

- يضيف خاصية ديناميكية `delete_url` لكل مرفق، لتسهيل استخدامها في القالب، بدل تكرار `{% url 'core:attachment_delete' att.pk %}`.

```python
        request = getattr(self, "request", None)
        next_url = request.get_full_path() if request else "/"
```

- يحدد `next_url` ليكون مسار الصفحة الحالية (مثلاً صفحة تفاصيل الفاتورة).

```python
        context["attachments"] = attachments
        context["attachments_count"] = attachments.count()
        context["attachment_form"] = AttachmentForm()
        context["attachment_content_type_id"] = ct.pk
        context["attachment_object_id"] = parent.pk
        context["attachment_next_url"] = next_url
        return context
```

- يحقن في الـ context:

  - `attachments`: قائمة المرفقات.
  - `attachments_count`: عدد المرفقات.
  - `attachment_form`: نموذج فارغ لرفع مرفق جديد.
  - `attachment_content_type_id`: الـ id الخاص بالموديل الأب.
  - `attachment_object_id`: الـ PK للكائن الأب.
  - `attachment_next_url`: رابط الصفحة الحالية (للرجوع بعد الرفع/الحذف).

### 3.3 مثال استخدام الـ Mixin مع DetailView

```python
from django.views.generic import DetailView
from core.views.attachments import AttachmentPanelMixin
from accounting.models import Invoice

class InvoiceDetailView(AttachmentPanelMixin, DetailView):
    model = Invoice
    template_name = "accounting/invoices/invoice_detail.html"
    context_object_name = "invoice"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context = self.inject_attachment_panel_context(context)
        return context
```

بهذه الطريقة:

- أي صفحة تفاصيل (Invoice, Order, Customer, ...) يمكنها دعم المرفقات بمجرد:
  - إضافتها إلى الـ view عبر `AttachmentPanelMixin`.
  - استدعاء `inject_attachment_panel_context` داخل `get_context_data`.
  - تضمين القالب الجزئي `_panel.html` في الـ template.

---

## 4. مسارات الـ URLs

في `core/urls.py`:

```python
from core.views.attachments import AttachmentCreateView, AttachmentDeleteView

app_name = "core"

urlpatterns = [
    # ...
    path("attachments/add/", AttachmentCreateView.as_view(), name="attachment_add"),
    path("attachments/<int:pk>/delete/", AttachmentDeleteView.as_view(), name="attachment_delete"),
]
```

- `core:attachment_add`:
  - لاستقبال POST من نموذج رفع المرفقات.
- `core:attachment_delete`:
  - لاستقبال POST لحذف (تعطيل) مرفق واحد.

تأكد من:

- أن `core` موجود في `INSTALLED_APPS`.
- أن ملف `core/urls.py` مضمّن (included) في ملف urls الرئيسي للمشروع.

---

## 5. القالب الجزئي `templates/core/attachments/_panel.html`

هذا القالب هو الـ panel الجاهز الذي يمكن تضمينه في أي صفحة تفاصيل.

```django
{% load i18n %}

<div class="card border-0 shadow-sm mt-3">
  <div class="card-body">
```

### 5.1 رأس الـ Panel

```django
    <div class="d-flex justify-content-between align-items-center mb-3">
      <div class="d-flex align-items-center gap-2">
        <h5 class="card-title mb-0">
          {% trans "المرفقات" %}
        </h5>
        <span class="badge bg-secondary">
          {{ attachments|length }} {% trans "مرفق(ات)" %}
        </span>
      </div>
    </div>
```

- يعرض عنوان "المرفقات" مع Badge بعدد المرفقات الحالية.

---

### 5.2 جدول عرض المرفقات

```django
    <div class="table-responsive mb-3">
      <table class="table table-sm align-middle mb-0">
        <thead class="table-light">
          <tr>
            <th>{% trans "الملف" %}</th>
            <th>{% trans "العنوان" %}</th>
            <th>{% trans "الوصف" %}</th>
            <th>{% trans "تم الرفع بواسطة" %}</th>
            <th>{% trans "تاريخ الرفع" %}</th>
            <th class="text-end"></th>
          </tr>
        </thead>
        <tbody>
        {% for att in attachments %}
```

#### 5.2.1 الأيقونة حسب نوع الملف + رابط التحميل

```django
          <tr>
            <td>
              {% with name=att.file.name %}
                {% with lower=name|lower %}
                  {% if lower|slice:"-4:" == ".pdf" %}
                    📄
                  {% elif lower|slice:"-4:" == ".png" or lower|slice:"-4:" == ".jpg" or lower|slice:"-5:" == ".jpeg" %}
                    🖼️
                  {% else %}
                    📎
                  {% endif %}
                {% endwith %}
                <a href="{{ att.file.url }}"
                   target="_blank"
                   class="small text-decoration-none"
                   title="{{ name }}">
                  {{ name|slice:"-40:" }}
                </a>
              {% endwith %}
            </td>
```

- يحدد الأيقونة حسب الامتداد:
  - PDF → 📄
  - PNG/JPG/JPEG → 🖼️
  - غير ذلك → 📎
- يعرض الرابط لفتح الملف في تبويب جديد (`target="_blank"`).
- يعرض آخر 40 حرفاً من اسم الملف لتجنب الطول الزائد.

#### 5.2.2 بقية أعمدة الجدول

```django
            <td class="small">
              {{ att.title|default:"—" }}
            </td>
            <td class="small">
              {{ att.description|default:"—" }}
            </td>
            <td class="small">
              {% if att.uploaded_by %}
                {{ att.uploaded_by.get_full_name|default:att.uploaded_by.username }}
              {% else %}
                <span class="text-muted">—</span>
              {% endif %}
            </td>
            <td class="small text-nowrap">
              {{ att.uploaded_at|date:"Y-m-d H:i" }}
            </td>
```

- يعرض العنوان، الوصف، اسم المستخدم الذي رفع، وتاريخ الرفع.

#### 5.2.3 زر الحذف

```django
            <td class="text-end">
              <form method="post"
                    action="{% url 'core:attachment_delete' att.pk %}"
                    onsubmit="return confirm('{% trans "هل أنت متأكد من حذف هذا المرفق؟" %}');"
                    class="d-inline">
                {% csrf_token %}
                <input type="hidden" name="next" value="{{ attachment_next_url }}">
                <button type="submit" class="btn btn-sm btn-outline-danger">
                  {% trans "حذف" %}
                </button>
              </form>
            </td>
          </tr>
        {% empty %}
          <tr>
            <td colspan="6" class="text-center text-muted small py-3">
              {% trans "لا توجد مرفقات حتى الآن." %}
            </td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
```

- لكل مرفق، يوجد فورم حذف منفصل:
  - `action` → `core:attachment_delete` مع `att.pk`.
  - يحتوي hidden input `next` للعودة لنفس الصفحة بعد الحذف.
- في حال عدم وجود مرفقات، يعرض سطر "لا توجد مرفقات حتى الآن.".

---

### 5.3 نموذج رفع مرفق جديد

```django
    <h6 class="mb-2">{% trans "إضافة مرفق جديد" %}</h6>
    <form method="post"
          action="{% url 'core:attachment_add' %}"
          enctype="multipart/form-data"
          class="row g-2 align-items-end">
      {% csrf_token %}
      <input type="hidden" name="content_type" value="{{ attachment_content_type_id }}">
      <input type="hidden" name="object_id" value="{{ attachment_object_id }}">
      <input type="hidden" name="next" value="{{ attachment_next_url }}">
```

- الفورم يرسل إلى فيو `AttachmentCreateView`.
- يحتوي على:
  - `content_type` (id) للكائن الأب.
  - `object_id` (pk) للكائن الأب.
  - `next` (الرابط الحالي).

#### 5.3.1 الحقول من `AttachmentForm`

```django
      <div class="col-md-4">
        <label class="form-label small" for="{{ attachment_form.file.id_for_label }}">
          {{ attachment_form.file.label }}
        </label>
        {{ attachment_form.file }}
        <div class="text-danger small">
          {{ attachment_form.file.errors }}
        </div>
      </div>

      <div class="col-md-3">
        <label class="form-label small" for="{{ attachment_form.title.id_for_label }}">
          {{ attachment_form.title.label }}
        </label>
        {{ attachment_form.title }}
        <div class="text-danger small">
          {{ attachment_form.title.errors }}
        </div>
      </div>

      <div class="col-md-4">
        <label class="form-label small" for="{{ attachment_form.description.id_for_label }}">
          {{ attachment_form.description.label }}
        </label>
        {{ attachment_form.description }}
        <div class="text-danger small">
          {{ attachment_form.description.errors }}
        </div>
      </div>

      <div class="col-md-1 d-grid">
        <button type="submit" class="btn btn-primary btn-sm">
          {% trans "رفع" %}
        </button>
      </div>
    </form>

  </div>
</div>
```

- الحقول:
  - `file`: اختيار الملف.
  - `title`: عنوان المرفق.
  - `description`: وصف اختياري.
- لكل حقل مكان لـ errors إن وجدت.

---

## 6. طريقة الاستخدام خطوة بخطوة

### 6.1 تهيئة الـ URLs في `core`

تأكد أن لديك في `core/urls.py`:

```python
from core.views.attachments import AttachmentCreateView, AttachmentDeleteView

app_name = "core"

urlpatterns = [
    # ...
    path("attachments/add/", AttachmentCreateView.as_view(), name="attachment_add"),
    path("attachments/<int:pk>/delete/", AttachmentDeleteView.as_view(), name="attachment_delete"),
]
```

وأن `core.urls` مضمّن في ملف urls الرئيسي للمشروع.

---

### 6.2 إضافة دعم المرفقات لأي DetailView

مثال: **تفاصيل فاتورة**

```python
# accounting/views.py

from django.views.generic import DetailView
from core.views.attachments import AttachmentPanelMixin
from accounting.models import Invoice

class InvoiceDetailView(AttachmentPanelMixin, DetailView):
    model = Invoice
    template_name = "accounting/invoices/invoice_detail.html"
    context_object_name = "invoice"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context = self.inject_attachment_panel_context(context)
        return context
```

يمكن تكرار نفس الفكرة مع:

- `OrderDetailView`
- `CustomerDetailView`
- `ProjectDetailView`
- وغيرها…

---

### 6.3 تضمين الـ panel في قالب التفاصيل

في `templates/accounting/invoices/invoice_detail.html`، أضف في المكان المناسب (مثلًا أسفل تفاصيل الفاتورة):

```django
{% include "core/attachments/_panel.html" %}
```

وسيعمل مباشرة إذا كنت قد:

- استخدمت `AttachmentPanelMixin` في الفيو.
- استدعيت `inject_attachment_panel_context` داخل `get_context_data`.

---

### 6.4 منطق الصلاحيات الحالي

- **رفع المرفقات:**

  - يتطلب تسجيل الدخول (`login_required`).

- **حذف المرفقات:**

  - يُسمح للـ staff (`is_staff=True`)، أو
  - للشخص نفسه الذي رفع المرفق (`attachment.uploaded_by == request.user`).

يمكنك تعديل منطق الصلاحيات لاحقًا في `AttachmentDeleteView` إذا احتجت قواعد مختلفة (مثلاً: صلاحيات خاصة بالزبون في البورتال).

---

## 7. أفكار تطوير مستقبلية

- إضافة فلترة في الـ Mixin:
  - لعرض فقط المرفقات `is_public=True` في واجهة الزبون.
- إضافة `GenericRelation` في الموديلات (Invoice, Order, ...):
  - لتسهيل الوصول من الجهة الأخرى: `invoice.attachments.all()`.
- توفير API باستخدام DRF:
  - لرفع وحذف واستعراض المرفقات عبر REST.
- دعم أنواع مرفقات خاصة:
  - مثل "صور المعرض" في المنتجات، أو "عقود" في العملاء، عبر حقل `type` إضافي.

بهذا يكون عندك **نظام مرفقات عام، قابل لإعادة الاستخدام**، مع panel جاهز، يمكن تركيبه بسهولة على أي موديل في المشروع.
