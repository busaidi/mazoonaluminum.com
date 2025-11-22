# Mazoon Aluminum Website (Django)

Multilingual (Arabic/English) website for mazoonaluminum.com built with Django and Bootstrap.

## Main features

- Home, About, Lab, Blog, Products, Contact pages
- Blog with comments
- Product listing
- Arabic as default language, English as secondary
- Language switcher in navbar
- Bootstrap 5 layout (CDN)

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```
```bash
pip install "Django>=5.2,<5.3"
```
```bash
python manage.py makemigrations
```
```bash
pip install -r requirements.txt
```
```bash
pip install --upgrade pip
```

```bash
python -m pip freeze > requirements.txt
```
```bash
python manage.py shell
```
```bash
python manage.py migrate
```
```bash
python manage.py createsuperuser
```
# admin hamed and agent users and accounting_staff_group
```bash
python manage.py seed_accounting_staff_group
```
```bash

python manage.py seed_users
```



```bash
python manage.py seed_hamed_user
```
```bash
python manage.py seed_agent_customer
```
```bash
python manage.py seed_website_data
```
```bash
python manage.py seed_accounts
```
```bash
python manage.py seed_journals
```
```bash
python manage.py runserver
```
```bash
python manage.py test ledger -v 2
```

Open:

- Arabic: http://127.0.0.1:8000/ar/
- English: http://127.0.0.1:8000/en/

## Translations

To regenerate messages (if you change text):

```bash
# Make sure gettext is installed (Ubuntu: sudo apt install gettext)
django-admin makemessages -l en
```
```bash
django-admin compilemessages
```

The current English translations are stored in `locale/en/LC_MESSAGES/django.po`.
