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

pip install "Django>=5.2,<5.3"

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open:

- Arabic: http://127.0.0.1:8000/ar/
- English: http://127.0.0.1:8000/en/

## Translations

To regenerate messages (if you change text):

```bash
# Make sure gettext is installed (Ubuntu: sudo apt install gettext)
django-admin makemessages -l en
django-admin compilemessages
```

The current English translations are stored in `locale/en/LC_MESSAGES/django.po`.
