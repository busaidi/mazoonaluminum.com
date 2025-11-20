"""
Compatibility wrapper around the central domain event bus in core.models.domain.

- استخدم core.models.domain.register_handler / dispatch_event مستقبلاً.
- هذا الملف فقط لأجل التوافق مع أي كود قديم كان يستورد من core.domain.dispatcher.
"""

from typing import Callable, Type

from core.models.domain import (
    DomainEvent,
    register_handler as _register_handler,
    dispatch_event as _dispatch_event,
)


def register_handler(event_type: Type[DomainEvent], handler: Callable[[DomainEvent], None]) -> None:
    """
    رابر بسيط حول core.models.domain.register_handler
    """
    _register_handler(event_type, handler)


def dispatch(event: DomainEvent) -> None:
    """
    رابر بسيط حول core.models.domain.dispatch_event
    """
    _dispatch_event(event)
