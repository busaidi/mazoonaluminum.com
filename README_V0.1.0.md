# Mazoon Aluminum Website (Django)

Multilingual (Arabic/English) ERP-style website (website + accounting + ledger + inventory) built with Django and Bootstrap.

- Default language: Arabic (العربية)
- Secondary language: English
- Responsive Bootstrap 5 layout

---

## Main Features

- Public Website:
  - Home, About, Lab, Blog, Products, Contact pages
  - Blog with comments
  - Product listing

- Core / ERP:
  - Accounting + ledger
  - Inventory + units of measure
  - Demo seed data for quick testing

---

## 1. Development Setup (Local)

### 1.1 Create virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # على Windows: .venv\Scripts\activate
```

### 1.2 Install dependencies

> يفضّل أولاً تحديث pip ثم تثبيت المتطلبات:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 1.3 Create `.env` for development

```bash
cat > .env << 'EOF'
DJANGO_SECRET_KEY=dev-secret-key-change-me-locally
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1 localhost
EOF
```

### 1.4 Apply migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 1.5 Seed initial/demo data (اختياري لكن مفيد)

ترتيب مقترح:

```bash
# مستخدمين أساسيين
python manage.py seed_users

# بيانات الموقع (صفحات، مقالات...)
python manage.py seed_website_data

# قيود يومية تجريبية
python manage.py seed_journals

# وحدات القياس
python manage.py seed_uom

# ديمو للمخزون (منتجات + مخازن + حركات)
python manage.py seed_inventory_demo

# حسابات الدفتر العام
python manage.py seed_accounts

# مجموعات المستخدمين والصلاحيات للمحاسبة
python manage.py seed_accounting_staff_group

# مستخدم حمد التجريبي
python manage.py seed_hamed_user

# مستخدم عميل (agent customer) للبورتال
python manage.py seed_agent_customer
```

### 1.6 Run development server

```bash
python manage.py runserver
```

ثم افتح:

- Arabic: http://127.0.0.1:8000/ar/
- English: http://127.0.0.1:8000/en/

---

## 2. Production Environment (.env example)

> مثال على إعداد `.env` في الإنتاج (مثلاً على `omanskylight.com`):

```bash
cat > .env << EOF
DJANGO_SECRET_KEY=$(openssl rand -hex 64)
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=omanskylight.com www.omanskylight.com 127.0.0.1
EOF
```

> ملاحظات:
> - هنا استخدمنا `EOF` بدون علامات اقتباس حتى يتم تنفيذ `$(openssl rand -hex 64)`.
> - استبدل الدومين بـ الدومين الخاص بك إن لزم.

---

## 3. Useful Management Commands

### 3.1 Create superuser

```bash
python manage.py createsuperuser
```

### 3.2 Open Django shell

```bash
python manage.py shell
```

### 3.3 Run tests (ledger app)

```bash
python manage.py test ledger -v 2
```

---

## 4. Translations

ملف الترجمة الإنجليزي موجود في:

- `locale/en/LC_MESSAGES/django.po`

لإنشاء/تحديث رسائل الترجمة:

```bash
# تأكد أن gettext مثبت (على Ubuntu مثلاً):
# sudo apt install gettext

django-admin makemessages -l en
django-admin compilemessages
```

---

## 5. Windows Notes

تحديث pip على Windows:

```bash
python.exe -m pip install --upgrade pip
```

---

## 6. Freezing Requirements (اختياري للمطور)

إذا حدّثت الحزم وتريد تحديث `requirements.txt`:

```bash
pip freeze > requirements.txt
```

> يفضّل عمل هذا فقط عندما تكون متأكدًا من الإصدارات التي تريد استخدامها في السيرفر.

---

## 7. OpenSSL Helper (Generate a secret key manually)

لو حاب تطلع secret key يدويًا:

```bash
openssl rand -hex 64
```

انسخ الناتج واستخدمه في `DJANGO_SECRET_KEY` في `.env`.
