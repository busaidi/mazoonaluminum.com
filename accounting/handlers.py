# accounting/handlers.py
import logging

from core.models.domain import register_handler
from accounting.domain import InvoiceCreated

logger = logging.getLogger(__name__)


def handle_invoice_created(event: InvoiceCreated) -> None:
    """
    مثال بسيط: نسجل في اللوق.
    لاحقًا نبدله بإنشاء Notification أو إرسال إيميل.
    """
    logger.info(
        "InvoiceCreated event: id=%s, serial=%s, customer_id=%s",
        event.invoice_id,
        event.serial,
        event.customer_id,
    )


# التسجيل مع event bus
register_handler(InvoiceCreated, handle_invoice_created)
