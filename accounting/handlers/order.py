# accounting/handlers/order.py
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.domain.dispatcher import register_handler
from accounting.domain import OrderCreated
from core.services.notifications import create_notification
from core.models import Notification

User = get_user_model()


@register_handler(OrderCreated)
def notify_staff_on_online_order_created(event: OrderCreated) -> None:
    """
    Domain event handler:
    لما ينشأ طلب أونلاين جديد → نرسل نتفيكشن لكل الستاف.
    """
    from accounting.models import Order  # import محلي لتفادي الـ circular

    try:
        order = (
            Order.objects
            .select_related("customer")
            .get(pk=event.order_id)
        )
    except Order.DoesNotExist:
        return

    # احتياط: نتأكد إنه أونلاين
    if not getattr(order, "is_online", False):
        return

    customer = order.customer

    verb = _(
        "New online order %(order_id)s from customer %(customer)s"
    ) % {
        "order_id": order.pk,
        "customer": getattr(customer, "name", str(customer)),
    }

    try:
        url = reverse("accounting:order_detail", kwargs={"pk": order.pk})
    except Exception:
        url = ""

    staff_users = User.objects.filter(is_staff=True, is_active=True)
    if not staff_users.exists():
        return

    for user in staff_users:
        create_notification(
            recipient=user,
            verb=verb,
            target=order,
            level=Notification.Levels.INFO,
            url=url,
        )
