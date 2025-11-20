# accounting/apps.py
from django.apps import AppConfig


class AccountingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounting"

    def ready(self) -> None:
        # المفروض هذا ينطبع مرّة واحدة عند تشغيل السيرفر
        print(">>> DEBUG: AccountingConfig.ready() called")

        from .domain import register_domain_handlers
        register_domain_handlers()
