from __future__ import annotations

from dataclasses import dataclass

from core.models.domain import DomainEvent, register_handler


# ==============================
# 1) Events
# ==============================

@dataclass(frozen=True)
class InvoiceCreated(DomainEvent):
    invoice_id: int
    serial: str


@dataclass(frozen=True)
class InvoiceUpdated(DomainEvent):
    invoice_id: int
    serial: str


# ==============================
# 2) Handlers
# ==============================

def invoice_created_notify_staff(event: InvoiceCreated) -> None:
    """
    Notify all staff users when a new invoice is created.
    """
    from django.contrib.auth import get_user_model
    from django.urls import reverse
    from django.utils.translation import gettext as _
    from django.contrib.contenttypes.models import ContentType

    from core.models import Notification
    from .models import Invoice

    User = get_user_model()

    invoice = Invoice.objects.filter(pk=event.invoice_id).first()
    if not invoice:
        return

    serial = getattr(invoice, "serial", None) or event.serial

    try:
        url = reverse("accounting:invoice_detail", kwargs={"serial": serial})
    except Exception:
        url = ""

    customer_label = getattr(invoice, "customer", None) or getattr(
        invoice, "customer_name", serial
    )

    verb = _("Invoice {serial} has been created for {customer}.").format(
        serial=serial,
        customer=getattr(customer_label, "name", customer_label),
    )

    ct = ContentType.objects.get_for_model(Invoice)
    staff_users = User.objects.filter(is_staff=True, is_active=True)

    for staff in staff_users:
        Notification.objects.create(
            recipient=staff,
            verb=verb,
            level=Notification.Levels.INFO,
            url=url,
            target_content_type=ct,
            target_object_id=str(invoice.pk),
        )


def invoice_updated_notify_staff(event: InvoiceUpdated) -> None:
    """
    Notify all staff users when an existing invoice is updated.
    (للتجربة فقط حالياً)
    """
    from django.contrib.auth import get_user_model
    from django.urls import reverse
    from django.utils.translation import gettext as _
    from django.contrib.contenttypes.models import ContentType

    from core.models import Notification
    from .models import Invoice

    User = get_user_model()

    invoice = Invoice.objects.filter(pk=event.invoice_id).first()
    if not invoice:
        return

    serial = getattr(invoice, "serial", None) or event.serial

    try:
        url = reverse("accounting:invoice_detail", kwargs={"serial": serial})
    except Exception:
        url = ""

    customer_label = getattr(invoice, "customer", None) or getattr(
        invoice, "customer_name", serial
    )

    verb = _("Invoice {serial} has been updated for {customer}.").format(
        serial=serial,
        customer=getattr(customer_label, "name", customer_label),
    )

    ct = ContentType.objects.get_for_model(Invoice)
    staff_users = User.objects.filter(is_staff=True, is_active=True)

    for staff in staff_users:
        Notification.objects.create(
            recipient=staff,
            verb=verb,
            level=Notification.Levels.INFO,
            url=url,
            target_content_type=ct,
            target_object_id=str(invoice.pk),
        )


# ==============================
# 3) Register handlers
# ==============================

def register_domain_handlers() -> None:
    register_handler(InvoiceCreated, invoice_created_notify_staff)
    register_handler(InvoiceUpdated, invoice_updated_notify_staff)
