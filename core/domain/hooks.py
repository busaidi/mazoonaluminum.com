# core/domain/hooks.py
from __future__ import annotations


def on_lifecycle(event_name: str):
    """
    Mark a model method as a lifecycle hook.

    Supported event names (by convention):
        - "created"  -> after first save()
        - "updated"  -> after subsequent save()
        - "deleted"  -> after delete()

    Example:

        from core.domain.hooks import on_lifecycle

        class Invoice(StatefulDomainModel):
            @on_lifecycle("created")
            def _on_created(self):
                self.emit(InvoiceCreated(invoice_id=self.pk, serial=self.serial))
    """

    def decorator(func):
        setattr(func, "__lifecycle_event__", event_name)
        return func

    return decorator


def on_transition(from_state: str, to_state: str, field_name: str = "status"):
    """
    Mark a model method as a state transition hook.

    - field_name: which field to track (default: "status").
    - from_state: old value.
    - to_state: new value.

    Example:

        class Invoice(StatefulDomainModel):
            class Status(models.TextChoices):
                DRAFT = "draft", "Draft"
                SENT = "sent", "Sent"

            @on_transition(Status.DRAFT, Status.SENT)
            def _on_sent(self):
                self.emit(InvoiceSent(invoice_id=self.pk, serial=self.serial))

    The hook will be called automatically when:
        old_status == from_state and new_status == to_state
    after save() completes and the DB transaction commits.
    """

    def decorator(func):
        setattr(func, "__transition__", (field_name, from_state, to_state))
        return func

    return decorator
