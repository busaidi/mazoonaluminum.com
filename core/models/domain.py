# core/models/domain.py
from __future__ import annotations

from typing import Any, Callable, DefaultDict, List, Type
from collections import defaultdict
import logging

from django.db import models

logger = logging.getLogger(__name__)

# ============================
# 1) Base class for events
# ============================


class DomainEvent:
    """
    Base class for all domain events.
    مجرد marker، الأحداث الفعلية تكون (غالباً) dataclasses ترث منه.
    """
    pass


EventHandler = Callable[[DomainEvent], None]

# ============================
# 2) Event bus بسيط (على مستوى الموديل)
# ============================

_handlers: DefaultDict[Type[DomainEvent], List[EventHandler]] = defaultdict(list)


def register_handler(event_type: Type[DomainEvent], handler: EventHandler) -> None:
    """
    تسجّل هاندلر لحدث معيّن.
    تستدعيها في apps.py أو في أي مكان مبكّر في الإقلاع.
    Example:
        from django.apps import AppConfig
        from core.models.domain import register_handler
        from accounting.domain import InvoiceCreated
        from accounting.handlers import handle_invoice_created

        register_handler(InvoiceCreated, handle_invoice_created)
    """
    _handlers[event_type].append(handler)


def dispatch_event(event: DomainEvent) -> None:
    """
    استدعاء كل الهاندلرز المسجّلة لنوع هذا الحدث.
    """
    for handler in _handlers.get(type(event), []):
        try:
            handler(event)
        except Exception:
            logger.exception("Error handling domain event %s", event)


def dispatch_events(events: List[DomainEvent]) -> None:
    """
    دالة مساعده لديسباتش أكثر من حدث مرّة واحدة.
    """
    for event in events:
        dispatch_event(event)


# ============================
# 3) StatefulDomainModel
# ============================


class StatefulDomainModel(models.Model):
    """
    Mixin abstract يضيف دعم Domain Events لأي موديل.

    - self.add_event(event): تضيف حدث جديد للكائن الحالي.
    - self.pull_events(): ترجّع كل الأحداث المتراكمة وتصفّي القائمة.

    الموديل اللي يرث منه:
        class Invoice(StatefulDomainModel, ...):
            ...

        self.add_event(InvoiceCreated(...))
    """

    class Meta:
        abstract = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # لستة الأحداث اللي تصير على هذا الكيان أثناء lifecycle الحالي
        self._pending_events: List[DomainEvent] = []

    # -------- API للأبناء --------

    def add_event(self, event: DomainEvent) -> None:
        """
        تستخدمها داخل الموديل:
            self.add_event(InvoiceCreated(...))
        """
        # احتياط لو صار override غريب
        if not hasattr(self, "_pending_events"):
            self._pending_events = []
        self._pending_events.append(event)

    def pull_events(self) -> List[DomainEvent]:
        """
        ترجع الأحداث وتفضّي اللستة.
        تستعمل من الـ service / model اللي مسؤول عن الديسباتش.
        مثال في Invoice.save():
            events = self.pull_events()
            if events:
                dispatch_events(events)
        """
        if not hasattr(self, "_pending_events"):
            return []
        events = list(self._pending_events)
        self._pending_events.clear()
        return events
