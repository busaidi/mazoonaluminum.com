# accounting/signals/notifications.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.translation import gettext as _, get_language
from core.services.notifications import create_notification
from core.models import Notification
from accounting.models import Invoice

User = get_user_model()

def strip_lang_prefix(path: str) -> str:
    """
    يشيل البادئة /ar/ أو /en/ (أو أي لغة حالية) من بداية الرابط،
    عشان نخزن في النوتفيكشن path "محايد لغة"، مثل: /accounting/invoices/1/
    """
    if not path:
        return path

    lang = get_language() or "en"  # اللغة المفعلّة وقت الـ reverse
    prefix = f"/{lang}"
    prefixed = f"{prefix}/"  # مثل: "/ar/"

    if path.startswith(prefixed):
        # نخليها تبدأ من بعد "/ar"
        return path[len(prefix):]  # يترك "/" الأولى بعد اللغة: "/accounting/..."

    return path


@receiver(post_save, sender=Invoice)
def invoice_created_notification(sender, instance, created, **kwargs):
    """
    Trigger notifications when a new invoice is created.

    - إشعار للزبون (إن كان مربوطاً بمستخدم).
    - إشعار لموظفي المحاسبة (مجموعة accounting_staff).
    """
    if not created:
        # ما نرسل تنبيه في حالة التعديل، فقط الإنشاء الأول
        return

    invoice = instance

    # ===========================
    # 1) تنبيه للزبون (Customer)
    # ===========================
    customer_user = getattr(invoice.customer, "user", None)

    if customer_user and customer_user.is_active:
        raw_customer_url = reverse(
            "portal:invoice_detail",
            kwargs={"number": invoice.number},
        )
        customer_url = strip_lang_prefix(raw_customer_url)

        create_notification(
            recipient=customer_user,
            verb=_("تم إصدار فاتورة رقم %(number)s") % {
                "number": invoice.number,
            },
            target=invoice,
            level=Notification.Levels.SUCCESS,
            url=customer_url,  # 👈 الآن بدون /ar أو /en
        )

    # ====================================
    # 2) تنبيه لموظفي المحاسبة (Staff)
    # ====================================

    raw_staff_url = reverse(
        "accounting:invoice_detail",
        kwargs={"number": invoice.number},
    )
    staff_url = strip_lang_prefix(raw_staff_url)

    staff_users = User.objects.filter(
        groups__name="accounting_staff",
        is_active=True,
    ).distinct()

    for staff in staff_users:
        create_notification(
            recipient=staff,
            verb=_("من هنا 001 جديدة (%(number)s) للزبون %(customer)s") % {
                "number": invoice.number,
                "customer": str(invoice.customer),
            },
            target=invoice,
            level=Notification.Levels.INFO,
            url=staff_url,  # 👈 path محايد لغة
        )

