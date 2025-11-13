
# 🗺️ **Mazoon Aluminum – ERP Lite (Website + Accounting + Portal) Roadmap**

## **النسخة: 1.0 – جاهزة للاستخدام داخل المشروع**

---

# ⚡ 0) المرحلة التأسيسية – هيكلة المشروع

### **إنشاء التطبيقات الأساسية:**
- `website` → الموقع العام (Home – Blog – Products – Contact)
- `accounting` → محاسبة مبسّطة (فواتير + دفعات)
- `portal` → بوابة الزبون (فواتير – دفعات – طلبات – تحديث بيانات)

### **إضافة التطبيقات في settings.py:**
```python
INSTALLED_APPS = [
    "website",
    "accounting",
    "portal",
]
```

### **ربط التطبيقات في urls.py:**
```python
urlpatterns += i18n_patterns(
    path("", include("website.urls")),
    path("accounting/", include("accounting.urls")),
    path("portal/", include("portal.urls")),
)
```

---

# 📦 1) المرحلة الأولى – إنشاء نماذج المحاسبة

## **Customer**
```python
class Customer(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, ...)
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True)
    company_name = models.CharField(max_length=255, blank=True)
```

## **Invoice**
```python
class Invoice(models.Model):
    customer = models.ForeignKey(Customer, ...)
    number = models.CharField(max_length=50, unique=True)
    issued_at = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=3)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    status = models.CharField(max_length=20, choices=[...])
```

## **Payment**
```python
class Payment(models.Model):
    customer = models.ForeignKey(Customer, ...)
    invoice = models.ForeignKey(Invoice, null=True, blank=True, ...)
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=3)
    notes = models.CharField(max_length=255, blank=True)
```

---

# 🛒 2) المرحلة الثانية – إعداد Product للبروفايلات

```python
class Product(models.Model):
    name_ar = models.CharField(max_length=255)
    name_en = models.CharField(max_length=255)
    description_ar = models.TextField(blank=True)
    description_en = models.TextField(blank=True)
    is_profile = models.BooleanField(default=False)
    default_price = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    slug = models.SlugField(unique=True)
```

---

# 👨‍💼 3) المرحلة الثالثة – واجهة الموظف خارج الـ Admin

- `/accounting/invoices/`
- `/accounting/invoices/new/`
- `/accounting/invoices/<number>/`

Views:
- InvoiceListView
- InvoiceCreateView
- InvoiceDetailView

صلاحيات:
```python
@user_passes_test(lambda u: u.groups.filter(name="accounting_staff").exists())
```

---

# 🧑‍💻 4) المرحلة الرابعة – الطلبات أونلاين

## Order
```python
class Order(models.Model):
    customer = ...
    created_at = ...
    status = ...
```

## OrderLine
```python
class OrderLine(models.Model):
    order = ...
    product = ...
    quantity = ...
    unit_price = ...
```

---

# 🔐 5) المرحلة الخامسة – بوابة الزبون Portal

Links:
- `/portal/invoices/`
- `/portal/payments/`
- `/portal/orders/`

---

# 🔑 6) المرحلة السادسة – Google OAuth

Install:
```
pip install django-allauth
```

Setup Google login.

---

# 📊 7) المرحلة السابعة – SEO

- website صفحات جاهزة بـ meta tags
- accounting + portal → SEO غير مهم

---

# 🧪 8) المرحلة الثامنة – Testing Checklist

✔ تسجيل زبون  
✔ إنشاء فاتورة  
✔ ظهور الفاتورة في portal  
✔ إنشاء دفعة  
✔ تجربة AR/EN  
✔ تجربة OAuth  

---

# 🎯 Final Summary

نظام منظم، قابل للتوسع، جاهز للـ Production.
