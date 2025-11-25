import os
from pathlib import Path

from dotenv import load_dotenv  # 👈 نحتاج python-dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------
#   .env
# ---------------------------------
# نحاول نحمّل .env من جذر المشروع (لو موجود)
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(env_path)

# ---------------------------------
#   أمان و Debug
# ---------------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me-in-development-only")

DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"

# مثال: "127.0.0.1 localhost omanskylight.com www.omanskylight.com"
_raw_hosts = os.getenv("DJANGO_ALLOWED_HOSTS", "")
if _raw_hosts.strip():
    ALLOWED_HOSTS = _raw_hosts.split()
else:
    # افتراضيًا في التطوير
    ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

INSTALLED_APPS = [
    # translation
    "modeltranslation",
    #Django Framework default
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Library for framework only
    "django.contrib.sitemaps",
    # My App
    "contacts.apps.ContactsConfig",
    "core.apps.CoreConfig",
    "website.apps.WebsiteConfig",
    "accounting.apps.AccountingConfig",
    "portal.apps.PortalConfig",
    "cart.apps.CartConfig",
    "ledger.apps.LedgerConfig",
    "inventory.apps.InventoryConfig",
    "uom.apps.UomConfig",
    "payments.apps.PaymentsConfig",
    "sales.apps.SalesConfig",
    "windowcad.apps.WindowcadConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mazoonaluminum.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                # notifications
                "core.context_processors.notifications.notifications_context",
            ],
        },
    },
]

WSGI_APPLICATION = "mazoonaluminum.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "ar"

LANGUAGES = [
    ("ar", "العربية"),
    ("en", "English"),
]

MODELTRANSLATION_DEFAULT_LANGUAGE = "ar"
MODELTRANSLATION_LANGUAGES = ("ar", "en")
MODELTRANSLATION_FALLBACK_LANGUAGES = {
    "default": ("ar", "en"),
}

LOCALE_PATHS = [
    BASE_DIR / "locale",
]

TIME_ZONE = "Asia/Muscat"
USE_I18N = True
USE_TZ = True

# -----------------------------
#   Static / Media
# -----------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

# مهم للإنتاج (collectstatic)
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
