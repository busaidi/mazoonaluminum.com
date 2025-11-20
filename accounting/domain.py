# accounting/domain.py
from dataclasses import dataclass

from core.models.domain import DomainEvent


@dataclass
class InvoiceCreated(DomainEvent):
    invoice_id: int
    serial: str
    customer_id: int
