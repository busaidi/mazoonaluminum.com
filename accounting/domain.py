# accounting/domain.py
from dataclasses import dataclass

from core.domain.events import DomainEvent


@dataclass(frozen=True)
class InvoiceCreated(DomainEvent):
    """
    Domain event: an invoice was created.
    """
    invoice_id: int
    serial: str


@dataclass(frozen=True)
class InvoiceSent(DomainEvent):
    """
    Domain event: an invoice was sent to the customer.
    (ستستخدمه لاحقًا مع on_transition لما تغيّر status من DRAFT إلى SENT)
    """
    invoice_id: int
    serial: str

@dataclass(frozen=True)
class OrderCreated(DomainEvent):
    """
    Domain event: an order was created (we will use it for online orders).
    """
    order_id: int
