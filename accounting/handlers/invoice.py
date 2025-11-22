# accounting/handlers/invoice.py
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from core.domain.dispatcher import register_handler
from accounting.domain import InvoiceCreated, InvoiceSent
from core.services.notifications import create_notification
from core.models import Notification  # لاستخدام مستويات الـ level

User = get_user_model()


@register_handler(InvoiceCreated)
def notify_staff_on_invoice_created(event: InvoiceCreated) -> None:
    """
    Domain event handler:
    Notify staff users when a new invoice is created.
    """

    from accounting.models import Invoice  # local import لتفادي الـ circular imports

    try:
        invoice = (
            Invoice.objects
            .select_related("customer")
            .get(pk=event.invoice_id)
        )
    except Invoice.DoesNotExist:
        # في حالة نادرة جدًا لو انحذفت الفاتورة قبل الهاندلر
        return

    # اختَر من تريد إبلاغه: كل الـ staff النشِطين
    staff_users = User.objects.filter(is_staff=True, is_active=True)
    if not staff_users.exists():
        return

    # نص قصير يعبّر عن الحدث (verb)
    verb = _(
        "New invoice %(serial)s created for %(customer)s "
        "with total %(amount).3f"
    ) % {
        "serial": invoice.serial,
        "customer": getattr(invoice.customer, "name", str(invoice.customer)),
        "amount": invoice.total_amount,
    }

    # رابط اختياري للفatura (لو عندك get_absolute_url)
    url = ""
    if hasattr(invoice, "get_absolute_url"):
        try:
            url = invoice.get_absolute_url()
        except Exception:
            url = ""

    # إنشاء Notification لكل موظف
    for user in staff_users:
        create_notification(
            recipient=user,
            verb=verb,
            target=invoice,
            level=Notification.Levels.INFO,
            url=url,
        )

@register_handler(InvoiceSent)
def notify_customer_on_invoice_sent(event: InvoiceSent) -> None:
    """
    Domain event handler:
    Notify the customer when an invoice is marked as SENT.
    """

    from accounting.models import Invoice  # local import لتفادي الدوران

    try:
        invoice = (
            Invoice.objects
            .select_related("customer")
            .get(pk=event.invoice_id)
        )
    except Invoice.DoesNotExist:
        return

    customer = invoice.customer

    # نفترض إن عندك علاقة customer.user تربط الزبون بحسابه في البورتال
    user = getattr(customer, "user", None)
    if user is None or not user.is_active:
        return

    verb = _(
        "Your invoice %(serial)s has been sent. "
        "Total amount: %(amount).3f"
    ) % {
        "serial": invoice.serial,
        "amount": invoice.total_amount,
    }

    url = ""
    if hasattr(invoice, "get_absolute_url"):
        try:
            url = invoice.get_absolute_url()
        except Exception:
            url = ""

    create_notification(
        recipient=user,
        verb=verb,
        target=invoice,
        level=Notification.Levels.INFO,
        url=url,
    )
