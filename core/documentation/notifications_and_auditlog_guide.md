# دليل شامل لاستخدام نظام الإشعارات (Notifications) وسجلّ التدقيق (AuditLog)
Mazoon Aluminum – Django ERP

> هذا الدليل يشرح كيف يعمل نظام الإشعارات وسجل التدقيق في مشروعك، وكيف تستخدمه في أي ميزة جديدة (الآن أو في المستقبل).
> الهدف: **تكون قادر تضيف إشعار + سجلّ تدقيق لأي حدث مهم في سطرين كود فقط.**

---

## 1. نظرة عامّة (High-level Overview)

حاليًا عندك نظامين مترابطين في تطبيقات المشروع:

1. **نظام الإشعارات – Notifications**
   - مخصص لتنبيه المستخدمين (الزبائن أو الموظفين) عن أحداث مهمة.
   - يظهر للمستخدم في:
     - أيقونة الجرس 🔔 في الـ Navbar.
     - صفحة كاملة لقائمة الإشعارات `/notifications/`.
   - مثال:

     - *"تم تأكيد طلبك رقم 15."*

     - *"تم إنشاء فاتورة جديدة من طلبك رقم 10."*

2. **سجل التدقيق – AuditLog**
   - مخصص لتسجيل كل الأحداث المهمة داخل النظام لأغراض التتبع والشفافية.
   - موجه **لك كمدير للنظام / محاسب / مسؤول تقنية** وليس للمستخدم النهائي.
   - يُعرض في صفحة خاصة بالموظفين فقط: `/audit-log/`.
   - مثال:

     - *"تأكيد الطلب رقم 15 من حالة PENDING إلى CONFIRMED بواسطة المستخدم X"*

     - *"إنشاء فاتورة INV-2025-0005 من الطلب 12"*


> الفكرة الذهبية:
> **كل حدث مهم = نتفيكشن للشخص المهتم + سجل AuditLog لك أنت.**

---

## 2. مكوّنات النظام في الكود

### 2.1 مكوّنات الإشعارات (Notifications)

- **Model**: `Notification` داخل تطبيق `core` (ملف `core/models/notification.py` أو مشابه حسب تنظيمك).
  أهم الحقول المستخدمة عمليًا:
  - `recipient`: المستخدم الذي يستقبل الإشعار (User).
  - `verb`: نص الإشعار (بالعربي غالبًا).
  - `is_read`: هل الإشعار مقروء أم لا.
  - `public_id`: UUID يُستخدم في الرابط العام (بدل الـ pk).
  - `created_at`: تاريخ ووقت إنشاء الإشعار.
  - `target`: علاقة عامة (GenericForeignKey) لأي كائن (طلب، فاتورة… إلخ).

- **Service**: دالة مخصصة لإنشاء الإشعارات في:

  - `core/services/notifications.py`

  - اسمها (المتفق عليه عندك): `create_notification()`


  مثال توقيع متوقَّع:

  ```python
  def create_notification(*, recipient, verb: str, actor=None, target=None, extra=None) -> Notification:
      ...
  ```

- **Context processor**:
  
  موجود في `core/context_processors.py` ومسجّل في `settings.py`:


  ```python
  'core.context_processors.notifications_context'
  ```


  هذا يمرّر المتغيرات التالية لكل التمبليتات:


  - `notif_unread_count`: عدد الإشعارات غير المقروءة للمستخدم الحالي.
  - `notif_recent`: قائمة بآخر عدد معيّن من الإشعارات (مثلاً آخر 5).


- **Views + URLs** في `core`:

  - `NotificationListView` → عرض قائمة الإشعارات.
  - `NotificationReadRedirectView` → يعلّم الإشعار كمقروء ثم يعيد التوجيه للهدف (order / invoice).
  - `notification_mark_all_read` → تعليم الكل كمقروء.
  - `notification_delete` → حذف إشعار معيّن.


- **Templates**:

  - Dropdown للجرس في `templates/base.html`.
  - صفحة كاملة للإشعارات: `templates/core/notifications/list.html` (أو مشابه).


---

### 2.2 مكوّنات سجل التدقيق (AuditLog)

- **Model**: `AuditLog` في `core/models/audit.py`:


  ```python
  class AuditLog(TimeStampedModel, SoftDeleteModel):
      class Action(models.TextChoices):
          CREATE = "create", _("إنشاء")
          UPDATE = "update", _("تعديل")
          DELETE = "delete", _("حذف")
          STATUS_CHANGE = "status_change", _("تغيير حالة")
          NOTIFICATION = "notification", _("إشعار")
          OTHER = "other", _("أخرى")

      action = models.CharField(max_length=32, choices=Action.choices)
      actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, ...)
      target_content_type = models.ForeignKey(ContentType, null=True, blank=True, ...)
      target_object_id = models.CharField(max_length=64, null=True, blank=True)
      target = GenericForeignKey("target_content_type", "target_object_id")
      message = models.TextField(blank=True)
      extra = models.JSONField(default=dict, blank=True)
  ```


  بالإضافة لـ `created_at`, `updated_at`, `is_deleted`, … من الـ `BaseModel`s اللي أنشأتها.


- **Service**: دالة جاهزة في `core/services/audit.py`:


  ```python
  from core.models import AuditLog

  def log_event(*, action: str, message: str = "", actor=None, target=None, extra=None) -> AuditLog:
      ...
  ```


- **View + URL**:

  - `AuditLogListView` في `core/views.py`
  - URL: `core:audit_log_list` (مثلًا على: `/audit-log/`)
  - محمي بـ `@staff_member_required` → **فقط المستخدمين `is_staff=True`** يقدروا يدخلوا.


- **Template**:

  - `templates/core/audit/log_list.html` لعرض الجدول + الفلاتر.


---

## 3. كيف أستخدم Notifications عمليًا؟

### 3.1 متى أستخدم الإشعارات؟

اسأل نفسك:


> هل هناك مستخدم سيهتم أن يعرف أن هذا الحدث حصل؟


إذا نعم، غالبًا تحتاج إشعار، مثل:


- زبون: تم تأكيد طلبه / إنشاء فاتورة / اعتماد فاتورة / وصول دفعة…
- موظف: طلب جديد من بوابة الزبون / دفع جديد / إلغاء طلب…


### 3.2 كيف أنشئ إشعار في الكود؟

1. استورد الدالة:


   ```python
   from core.services.notifications import create_notification
   ```


2. استخدمها في الحدث المناسب، مثال: بعد تأكيد طلب من قبل الموظف:


   ```python
   customer_user = getattr(order.customer, "user", None)
   if customer_user is not None:
       create_notification(
           recipient=customer_user,
           verb=_("تم تأكيد طلبك رقم %(number)s.") % {"number": order.pk},
           target=order,
       )
   ```


- `recipient`: مستخدم النظام الذي سيظهر له الإشعار في الجرس.
- `verb`: نص الإشعار (مترجم بالعربي).
- `target`: (اختياري لكن مهم) كائن الطلب / الفاتورة… عشان رابط الإشعار يفتح صفحة هذا الكائن.


### 3.3 كيف تظهر الإشعارات للمستخدم؟

1. **في الـ Navbar (الجرس)** – داخل `base.html`، مثال مبسّط:


   ```html
   {% if user.is_authenticated %}
   <li class="nav-item dropdown me-2">
     <a class="nav-link position-relative" href="#" id="navbarNotificationsDropdown"
        role="button" data-bs-toggle="dropdown" aria-expanded="false">
       <i class="bi bi-bell"></i>
       {% if notif_unread_count %}
         <span class="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger">
           {{ notif_unread_count }}
         </span>
       {% endif %}
     </a>

     <div class="dropdown-menu dropdown-menu-end dropdown-menu-notifications shadow-sm small"
          aria-labelledby="navbarNotificationsDropdown"
          style="min-width: 320px; max-height: 400px; overflow-y: auto;">

       <div class="px-3 py-2 border-bottom d-flex justify-content-between align-items-center">
         <span class="fw-semibold">{% trans "الإشعارات" %}</span>
         <a href="{% url 'core:notification_list' %}" class="text-decoration-none small text-muted">
           {% trans "عرض الكل" %}
         </a>
       </div>

       {% if notif_recent %}
         {% for n in notif_recent %}
           {% if n.public_id %}
             <a class="dropdown-item d-flex flex-column gap-1 py-2 {% if not n.is_read %}fw-semibold{% endif %}"
                href="{% url 'core:notification_read_redirect' public_id=n.public_id %}">
           {% else %}
             <a class="dropdown-item d-flex flex-column gap-1 py-2"
                href="{% url 'core:notification_list' %}">
           {% endif %}
               <span class="small">{{ n.verb }}</span>
               <span class="text-muted text-xs">
                 {{ n.created_at|date:"Y-m-d H:i" }}
               </span>
             </a>
           {% if not forloop.last %}
             <div class="dropdown-divider my-0"></div>
           {% endif %}
         {% endfor %}
       {% else %}
         <div class="px-3 py-3 text-muted small">
           {% trans "لا توجد إشعارات حالياً." %}
         </div>
       {% endif %}
     </div>
   </li>
   {% endif %}
   ```


2. **في صفحة الإشعارات الكاملة**:
  
   - تعرض جدول/قائمة بكل الإشعارات، مع زر:

     - "تحديد الكل كمقروء"

     - زر حذف لكل إشعار


### 3.4 ماذا يحدث عند الضغط على الإشعار؟

- الـ `NotificationReadRedirectView` يقوم بـ:

  1. تعليم الإشعار كمقروء (`is_read=True`).
  2. تحديد رابط الهدف (مثلاً صفحة الطلب أو الفاتورة) من خلال `target` أو `extra`.
  3. إعادة التوجيه للصفحة المناسبة.


بهذا الشكل، المستخدم يحس أن النظام "حي" وربط الأحداث واضح.


---

## 4. كيف أستخدم AuditLog عمليًا؟

### 4.1 متى أستخدم سجل التدقيق؟

أي حدث تحس إنه مهم للمحاسبة/الإدارة/المراجعة، مثل:


- تغيير حالة طلب أو فاتورة.
- إنشاء فاتورة من طلب.
- إلغاء ترحيل فاتورة.
- تعديل دفعة/سند.
- حذف بيانات حساسة.


### 4.2 كيف تسجل سجل تدقيق؟

1. استورد:


   ```python
   from core.models import AuditLog
   from core.services.audit import log_event
   ```


2. استخدم `log_event`، مثال: عند اعتماد فاتورة:

   ```python
   log_event(
    action=AuditLog.Action.STATUS_CHANGE,
    message=f"اعتماد الفاتورة {invoice.serial} وترحيلها إلى دفتر الأستاذ.",
    actor=request.user,
    target=invoice,
    extra={
        "old_status": old_status,
        "new_status": invoice.status,
        "source": "invoice_confirm_view",
    },
)
   ```


البارامترات:

- `action`: نوع العملية (من `AuditLog.Action` أو نص عادي).
- `message`: وصف عربي واضح للحدث.
- `actor`: المستخدم الذي نفّذ الحدث (`request.user` غالبًا).
- `target`: الكائن المعني (فاتورة، طلب…).
- `extra`: JSON حر لأي بيانات إضافية تحتاجها عند المراجعة.


### 4.3 كيف أقرأ السجل؟

- ادخل على صفحة: `/audit-log/` (أو `ar/audit-log/` حسب اللغات).
- راح تشوف:

  - تاريخ/وقت
  - العملية
  - المستخدم
  - الهدف
  - الوصف

- يوجد فلاتر بسيطة (حسب ما طبقت):

  - `?action=create`
  - `?q=نص` للبحث في الوصف
  - `?user=<id>` لتصفية حسب المستخدم


> هذه الصفحة هي عينك على النظام: أي شيء يصير في الطلبات والفواتير والقيود، تقدر ترجع له من هنا.


---

## 5. ربط الإشعارات + سجل التدقيق في حدث واحد

بدل ما تكتب كل مرة:


```python
log_event(...)
create_notification(...)
```


نقدر نستخدم **Helper واحد** يجمع الاثنين.


### 5.1 (اختياري) Helper: `notify_and_log`

أنشئ ملف جديد مثلاً:
`core/services/events.py` وضع فيه:


```python
from __future__ import annotations

from typing import Any, Optional

from core.models import AuditLog
from core.services.audit import log_event
from core.services.notifications import create_notification


def notify_and_log(
    *,
    actor,
    recipient,
    verb: str,
    target: Optional[Any] = None,
    action: str = AuditLog.Action.OTHER,
    message: str = "",
    extra: Optional[dict] = None,
):
    """
    Convenience helper to:
    - create a notification for recipient
    - create an audit log entry for the same event
    """

    # 1) Create notification
    notification = create_notification(
        recipient=recipient,
        verb=verb,
        actor=actor,
        target=target,
    )

    # 2) Create audit log
    log_event(
        action=action,
        message=message or verb,
        actor=actor,
        target=target,
        extra=(extra or {}) | {
            "notification_id": notification.id,
        },
    )

    return notification
```

### 5.2 استخدام `notify_and_log`

مثال عند إنشاء فاتورة من طلب:

```python
from core.services.events import notify_and_log

invoice = convert_order_to_invoice(order)

customer_user = getattr(order.customer, "user", None)
if customer_user is not None:
    notify_and_log(
        actor=request.user,
        recipient=customer_user,
        verb=_("تم إنشاء فاتورة جديدة برقم %(number)s من طلبك.") % {
            "number": invoice.serial
        },
        target=invoice,
        action=AuditLog.Action.CREATE,
        message=_("تم إنشاء فاتورة من الطلب رقم %(pk)s برقم فاتورة %(number)s.") % {
            "pk": order.pk,
            "number": invoice.serial,
        },
        extra={
            "order_id": order.pk,
            "invoice_number": invoice.serial,
            "source": "order_to_invoice",
        },
    )
```

الآن:

- الإشعار يُرسل للزبون.
- سجل التدقيق يُسجّل لحدث الإنشاء.
- كل هذا بدالة واحدة.


---

## 6. أمثلة من النظام الحالي (Mazoon Aluminum)

### 6.1 إنشاء طلب من بوابة الزبون (PortalOrderCreateView)

المنطقي:

- الزبون يرسل الطلب → إشعار للـ staff (مثلاً محاسبة).
- سجل تدقيق يذكر أن زبون X أنشأ طلب أونلاين.


ممكن تضيف في `form_valid` في `PortalOrderCreateView`:


```python
from django.contrib.auth import get_user_model
from core.services.events import notify_and_log
from core.models import AuditLog

User = get_user_model()

# ... بعد إنشاء order بنجاح:
staff_qs = User.objects.filter(is_staff=True)

for staff_user in staff_qs:
    notify_and_log(
        actor=self.request.user,
        recipient=staff_user,
        verb=_("تم إنشاء طلب جديد من بوابة الزبون (رقم: %(pk)s).") % {
            "pk": order.pk
        },
        target=order,
        action=AuditLog.Action.CREATE,
        message=_("طلب جديد عبر البوابة من الزبون %(customer)s (رقم الطلب: %(pk)s).") % {
            "customer": order.customer,
            "pk": order.pk,
        },
        extra={
            "source": "portal_order_create",
            "is_online": True,
        },
    )
```

### 6.2 تأكيد طلب من شاشة المحاسبة (staff_order_confirm)

- إشعار للزبون أن طلبه تم تأكيده.
- سجل تدقيق بتغيير حالة الطلب.


```python
from core.services.events import notify_and_log
from core.models import AuditLog

# بعد order.save(...)
customer_user = getattr(order.customer, "user", None)
if customer_user is not None:
    notify_and_log(
        actor=request.user,
        recipient=customer_user,
        verb=_("تم تأكيد طلبك رقم %(number)s.") % {"number": order.pk},
        target=order,
        action=AuditLog.Action.STATUS_CHANGE,
        message=_("تأكيد الطلب رقم %(pk)s من %(old)s إلى %(new)s.") % {
            "pk": order.pk,
            "old": old_status,
            "new": order.status,
        },
        extra={
            "old_status": old_status,
            "new_status": order.status,
            "source": "staff_order_confirm",
        },
    )
```

### 6.3 اعتماد فاتورة (invoice_confirm_view)

- إشعار للزبون أن فاتورته تم اعتمادها وترحيلها.
- سجل تدقيق مع رقم القيد المحاسبي.

```python
notify_and_log(
    actor=request.user,
    recipient=customer_user,
    verb=_("تم اعتماد فاتورتك رقم %(number)s وترحيلها في النظام.") % {
        "number": invoice.serial
    },
    target=invoice,
    action=AuditLog.Action.STATUS_CHANGE,
    message=f"اعتماد الفاتورة {invoice.serial} وترحيلها (قيد: {entry.serial}).",
    extra={
        "old_status": old_status,
        "new_status": invoice.status,
        "journal_entry_number": entry.serial,
        "source": "invoice_confirm_view",
    },
)
```

---

## 7. نمط عام لإضافة أي حدث جديد (Checklist)

كلما تبني ميزة جديدة (مثلاً: إرجاع بضاعة، إلغاء فاتورة، خصم، …) اتبع التالي:


1. حدّد:
  
   - من هو الـ **actor**؟ → غالبًا `request.user`
   - من هو الـ **recipient** (إن احتجنا إشعار)؟ → زبون / موظف آخر
   - ما هو الـ **target** (الشيء المعني)؟ → Order, Invoice, Payment…

2. اكتب جملة عربية واضحة للحدث:
   - للـ Notification: قصيرة وواضحة.
   - لسجل التدقيق: ممكن تكون أطول أو نفسها.

3. قرر نوع الـ action في AuditLog:
   - `CREATE`, `UPDATE`, `DELETE`, `STATUS_CHANGE`, `OTHER`…

4. أضف استدعاء واحد لـ `notify_and_log` (أو `log_event` + `create_notification`):

   ```python
   notify_and_log(
       actor=request.user,
       recipient=some_user,
       verb=_("نص الإشعار..."),
       target=some_object,
       action=AuditLog.Action.STATUS_CHANGE,
       message=_("وصف أوضح لسجل التدقيق..."),
       extra={"source": "اسم_الفيو_أو_الخدمة"},
   )
   ```

5. اختبر السيناريو من الطرفين:
   - هل يظهر الإشعار في الجرس؟
   - هل يمكن فتحه والذهاب للهدف؟
   - هل سجّل الحدث في `/audit-log/` بشكل منطقي؟


---

## 8. أفضل الممارسات (Best Practices)

- **لا ترسل إشعارات كثيرة بلا داعي**  
  الإشعارات لازم تمثّل أحداث مهمة، عشان المستخدم ما يتجاهلها.

- **استخدم `extra` بحكمة**  
  مثلاً احفظ فيها:

  - `source`: من أين جاء الحدث (اسم الفيو/الخدمة).
  - `old_status` / `new_status`.
  - أرقام القيود / أرقام العمليات الأخرى.

- **حافظ على نصوص عربية واضحة ومختصرة**  
  - للمستخدم → رسائل قصيرة.
  - لسجل التدقيق → مسموح تكون أطول لكن بدون حشو.

- **استخدم نفس الدليل هذا كمرجع**  
  لو بعد فترة نسيت كيف تربط؛ افتح ملف الدليل في المشروع.


---

## 9. أين أضع هذا الدليل في المشروع؟

اقترح تحفظ هذا الملف (الذي تقرأه الآن) داخل مجلد `docs/` في مشروعك:


```text
mazoonaluminum.com/
├── core/
├── accounting/
├── portal/
├── ...
└── docs/
    └── notifications_and_auditlog_guide.md
```


بهذا الشكل:

- أي مطوّر يشتغل معك مستقبلاً يقدر يفتح الملف ويفهم النظام بسرعة.
- أنت نفسك بعد أشهر لو نسيت بعض التفاصيل، تفتح هذا الملف كمرجع سريع.

---

انتهى الدليل ✅  
أي وقت تحب نضيف Feature جديدة (مثلاً: ربط مع WhatsApp، أو netflow بين الـ ledger والـ notifications)، نقدر نستخدم نفس البنية هذه كـ “Event System” بسيط يدعم الإشعارات + سجلات التدقيق بدون تعقيد.
