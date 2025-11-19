
# نظام المرفقات (Attachments) في مشروع Mazoon Aluminum

هذا المستند يشرح كيف يعمل نظام المرفقات الذي بنيناه في **core**، وكيف يتكامل مع شاشة الفاتورة في **accounting**، من لحظة فتح صفحة الفاتورة إلى رفع/حذف المرفق وعرضه في القالب.

---

## 1. الهدف من نظام المرفقات

- توفير طريقة عامة لربط ملفات (PDF، صور، Word، …) بأي كيان في النظام:
  - فاتورة (Invoice)
  - أمر بيع (Order)
  - لاحقًا: مشتريات، Bill، مشروع، عميل، …
- يكون النظام:
  - **عام (Generic)**: لا يحتاج حقل ForeignKey ثابت لكل موديل.
  - **قابل لإعادة الاستخدام**: نفس الكود يخدم أكثر من تطبيق.
  - **آمن ومنظّم**: مسار رفع واضح، صلاحيات حذف، فحص حجم ونوع الملف.

---

## 2. مكوّنات النظام

1. **موديل**: `core.models.Attachment`  
2. **فورم**: `core.forms.AttachmentForm`  
3. **فيوز عامة**:
   - `AttachmentParentMixin`
   - `BaseAttachmentCreateView`
   - `BaseAttachmentDeleteView`
4. **فيوز خاصة بالفاتورة**:
   - `InvoiceAttachmentCreateView`
   - `InvoiceAttachmentDeleteView`
   - `InvoiceDetailView`
5. **روابط URLs**
6. **قالب جزئي**  
   `templates/core/attachments/_invoice_panel.html`
7. **استدعاء البانل في قالب الفاتورة**

---

## 3. موديل Attachment

الموديل موجود في:

`core/models/attachments.py`

### أهم الحقول:

- `content_type + object_id + content_object`  
  - هذه هي GenericForeignKey  
  - تربط المرفق بأي موديل آخر.

- `file`  
  - الملف نفسه داخل media  
  - المسار يُنشأ عبر `attachment_upload_to`  
  - مثال:  
    `attachments/accounting/invoice/15/file.pdf`

- `title`, `description`, `uploaded_by`, `uploaded_at`

- `is_public`  
- `is_active` (Soft Delete)

### دالة المسار attachment_upload_to

تنظم التخزين حسب:
- التطبيق
- اسم الموديل
- رقم الكيان (object_id)

---

## 4. الفورم AttachmentForm

المكان:  
`core/forms.py`

### الميزات:
- يتحقق من نوع الملف
- يتحقق من حجم الملف
- يستخدم لرفع مرفق واحد بكل بساطة

---

## 5. الفيوز العامة في core

المكان:  
`core/views/attachments.py`

### 5.1 AttachmentParentMixin

يوفّر:
- معرفة الكيان الأب (Invoice, Order, ...)
- جلبه بالبحث عبر:
  - اسم kwarg في URL
  - اسم حقل lookup في الموديل
- تكوين رابط النجاح بعد الإضافة/الحذف

الإعدادات تضبط في الكلاس الابن:
- `attachment_parent_model`
- `attachment_parent_lookup_url_kwarg`
- `attachment_parent_lookup_field`
- `attachment_success_url_name`

---

### 5.2 BaseAttachmentCreateView

وظيفته:
1. جلب الكيان الأب
2. بناء الفورم من POST + FILES
3. إذا صحيح:
   - إنشاء Attachment
   - ربطه بالكيان عبر GenericForeignKey
   - وضع uploaded_by
4. حفظه
5. إعادة التوجيه إلى صفحة الفاتورة (أو الأب)

---

### 5.3 BaseAttachmentDeleteView

- يجلب المرفق المرتبط فقط بالكيان الأب
- يتحقق من صلاحية الحذف:
  - المستخدم staff
  - أو نفس المستخدم الذي رفع الملف
- يعمل "Soft delete"
- يرجع لصفحة الفاتورة

---

## 6. فيوز المرفقات الخاصة بالفاتورة

في `accounting/views.py`:

```python
class InvoiceAttachmentCreateView(AccountingSectionMixin, BaseAttachmentCreateView):
    section = "invoices"
    attachment_parent_model = Invoice
    attachment_parent_lookup_url_kwarg = "number"
    attachment_parent_lookup_field = "number"
    attachment_success_url_name = "accounting:invoice_detail"
```

```python
class InvoiceAttachmentDeleteView(AccountingSectionMixin, BaseAttachmentDeleteView):
    section = "invoices"
    attachment_parent_model = Invoice
    attachment_parent_lookup_url_kwarg = "number"
    attachment_parent_lookup_field = "number"
    attachment_success_url_name = "accounting:invoice_detail"
```

---

## 7. روابط URLs

في `accounting/urls.py`:

```python
path(
    "invoices/<str:number>/attachments/add/",
    views.InvoiceAttachmentCreateView.as_view(),
    name="invoice_add_attachment",
),
path(
    "invoices/<str:number>/attachments/<int:pk>/delete/",
    views.InvoiceAttachmentDeleteView.as_view(),
    name="invoice_delete_attachment",
),
```

---

## 8. القالب الجزئي _invoice_panel.html

وظيفته:
- عرض عدد المرفقات (Badge)
- عرض جدول بالمرفقات
- عرض أيقونة حسب نوع الملف (PDF / صورة / غيرها)
- زر حذف لكل مرفق
- فورم رفع مرفق جديد

يستقبل المتغيرات:
- `attachments`
- `attachments_count`
- `attachment_form`
- `invoice`
- `invoice_add_attachment_url`

---

## 9. ربط البانل بالقالب الرئيسي للفاتورة

في:

`templates/accounting/invoices/detail.html`

أضف:

```django
{% include "core/attachments/_invoice_panel.html" %}
```

وبهذا:
- البانل يظهر
- رفع ملف يعمل
- حذف يعمل
- لا حاجة لتكرار أي كود في التطبيق

---

## 10. إضافة مرفقات لأي موديل آخر (مثل Order)

فقط أنشئ:

```python
class OrderAttachmentCreateView(BaseAttachmentCreateView):
    attachment_parent_model = Order
    attachment_parent_lookup_url_kwarg = "pk"
    attachment_parent_lookup_field = "pk"
    attachment_success_url_name = "accounting:order_detail"
```

و:

```python
class OrderAttachmentDeleteView(BaseAttachmentDeleteView):
    attachment_parent_model = Order
    attachment_parent_lookup_url_kwarg = "pk"
    attachment_parent_lookup_field = "pk"
    attachment_success_url_name = "accounting:order_detail"
```

تضيف URLs  
وتستدعي نفس البانل في `order_detail.html`.

**بدون تغيير سطر واحد في core**.

---

## 11. النظام جاهز للتوسّع

لاحقًا يمكن إضافة:
- Notifications  
- Audit Log  
- Attachments في Portal  
- Attachments في Projects  
- Permissions متقدمة  
- Previews للملفات والصور  
- Viewer داخل النظام  

وكل هذا بدون تكرار أي جزء من الكود.

---

# خاتمة

نظام المرفقات الآن:

- عام  
- قوي  
- قابل للتوسع  
- قابل لإعادة الاستخدام  
- آمن  
- يندمج مع أي موديل بسهولة  

ويعمل بنفس أسلوب Odoo ولكن بمستوى أبسط وأخف على النظام.

