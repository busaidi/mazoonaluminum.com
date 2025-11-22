from django.apps import AppConfig


class AccountingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounting"

    def ready(self):
        """
        Load domain event handlers for the accounting app.

        This ensures that:
        - InvoiceCreated handlers
        - InvoiceSent handlers (future)
        - Payment handlers

        are registered at Django startup.

        Without this import, the handlers will never register
        because @register_handler only works if the module is imported.

        Important:
        - Import ONLY handler modules here.
        - Do NOT import models or heavy stuff to avoid circular imports.
        """
        import accounting.handlers  # noqa
