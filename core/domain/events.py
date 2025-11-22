# core/domain/events.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """
    Base class for all domain events.

    - Inherit from this class for concrete domain events.
    - Example:
        @dataclass(frozen=True)
        class InvoiceSent(DomainEvent):
            invoice_id: int
            serial: str
    """
    occurred_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
