# core/models/domain.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, DefaultDict, List, Type
from collections import defaultdict
import logging

from django.db import models

logger = logging.getLogger(__name__)


class DomainEvent:
    """
    Base class for all domain events.
    مجرد marker، الأحداث الفعلية بتكون dataclasses ترث منه.
    """
    pass


EventHandler = Callable[[DomainEvent], None]


# ============================
# Event bus
# ============================

_handlers: DefaultDict[Type[DomainEvent], List[EventHandler]] = defaultdict(list)


def register_handler(event_type: Type[DomainEvent], handler: EventHandler) -> None:
    _handlers[event_type].append(handler)


def dispatch_event(event: DomainEvent) -> None:
    for handler in _handlers.get(type(event), []):
        try:
            handler(event)
        except Exception:
            logger.exception("Error handling domain event %s", event)


def dispatch_events(events: List[DomainEvent]) -> None:
    for event in events:
        dispatch_event(event)


# ============================
# DomainModel + StatefulDomainModel
# ============================

class DomainModel(models.Model):
    """
    Base abstract model يدعم emit(event)
    """

    class Meta:
        abstract = True

    def emit(self, event: DomainEvent) -> None:
        """
        استدعاء الهاندلرز مباشرة (synchronous).
        """
        dispatch_event(event)


class StatefulDomainModel(DomainModel):
    """
    Abstract mixin يجمع:
    - pending events (للاستخدام المستقبلي)
    - منطق change_state القديم (state_field_name + on_state_changed)
    """

    class Meta:
        abstract = True

    # ========= pending events (لو حبيت تستخدمها لاحقاً) =========
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pending_events: list[DomainEvent] = []

    def add_event(self, event: DomainEvent) -> None:
        self._pending_events.append(event)

    def pull_events(self) -> list[DomainEvent]:
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    # ========= state handling API (من النسخة القديمة) =========
    state_field_name = "state"

    def _get_state(self) -> Any:
        return getattr(self, self.state_field_name)

    def _set_state(self, value: Any) -> None:
        setattr(self, self.state_field_name, value)

    def change_state(self, new: Any, *, emit_events: bool = True, save: bool = True) -> None:
        """
        يغيّر الحالة ويحفظ الحقل، ثم ينادي on_state_changed(old, new) إن لزم.
        """
        old = self._get_state()
        if old == new:
            return

        self._set_state(new)

        if save:
            self.save(update_fields=[self.state_field_name])

        if emit_events:
            self.on_state_changed(old, new)

    def on_state_changed(self, old: Any, new: Any) -> None:
        """
        Hook يمكن override في الموديل (مثل Invoice).
        """
        pass
