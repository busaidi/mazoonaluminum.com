# core/domain/dispatcher.py
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable, DefaultDict, Dict, List, Type, TypeVar

from .events import DomainEvent

logger = logging.getLogger(__name__)

EventT = TypeVar("EventT", bound=DomainEvent)
Handler = Callable[[EventT], None]


class DomainEventDispatcher:
    """
    Simple in-process domain event dispatcher.

    Usage:

        from core.domain.dispatcher import register_handler, emit

        @register_handler(InvoiceSent)
        def handle_invoice_sent(event: InvoiceSent) -> None:
            ...

        emit(InvoiceSent(invoice_id=1, serial="INV-2025-0001"))
    """

    def __init__(self) -> None:
        # Mapping: { EventClass -> [handler_fn, handler_fn, ...] }
        self._handlers: DefaultDict[Type[DomainEvent], List[Handler]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register_handler(self, event_type: Type[EventT]):
        """
        Decorator to register a handler for the given event type.

        Example:
            @dispatcher.register_handler(InvoiceSent)
            def handle(event: InvoiceSent):
                ...
        """

        def decorator(func: Handler) -> Handler:
            self._handlers[event_type].append(func)
            logger.debug(
                "Registered domain event handler %s for %s",
                func.__name__,
                event_type.__name__,
            )
            return func

        return decorator

    # ------------------------------------------------------------------
    # Emitting
    # ------------------------------------------------------------------
    def emit(self, event: DomainEvent) -> None:
        """
        Dispatch the given domain event to all registered handlers.

        - Handlers are executed in-process, synchronously.
        - Exceptions in one handler are logged and do not stop other handlers.
        """
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])

        if not handlers:
            logger.debug("No handlers registered for event %s", event_type.__name__)
            return

        logger.debug(
            "Emitting event %s to %d handler(s)",
            event_type.__name__,
            len(handlers),
        )

        for handler in handlers:
            try:
                handler(event)  # type: ignore[arg-type]
            except Exception:
                logger.exception(
                    "Error while handling event %s in handler %s",
                    event_type.__name__,
                    handler.__name__,
                )


# Global singleton dispatcher (sufficient for a Django monolith)
dispatcher = DomainEventDispatcher()

# Convenience API
register_handler = dispatcher.register_handler
emit = dispatcher.emit
