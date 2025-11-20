from django.apps import AppConfig


class AccountingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounting"

    def ready(self):
        """
        Loads:
        - Django signals (notifications)
        - Domain event handlers
        Everything is imported lazily during app startup.
        """
        # --- تحميل signals التقليدية (تنبيهات الطلبات) ---
        try:
            import accounting.signals.notifications  # noqa
        except Exception:
            # نتجنب كراش إذا missing في dev
            pass

        # --- تحميل domain event handlers ---
        try:
            import accounting.handlers  # noqa  ← هنا الدومين
        except Exception:
            pass
