# contacts/apps.py
from django.apps import AppConfig


class ContactsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contacts"
    verbose_name = "Contacts / الكونتاكتس"

    def ready(self):
        # مهم عشان modeltranslation يقرأ تعريف الترجمة
        from . import translation  # noqa
