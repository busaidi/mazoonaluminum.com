# core/services/audit.py
from __future__ import annotations

from typing import Any, Optional

from django.contrib.contenttypes.models import ContentType

from core.models import AuditLog


def log_event(
    *,
    action: str,
    message: str = "",
    actor=None,
    target: Optional[Any] = None,
    extra: Optional[dict] = None,
) -> AuditLog:
    """
    Create an audit log entry.

    - action: one of AuditLog.Action.* values or any string
    - message: human-readable description (Arabic is fine)
    - actor: a User instance or None
    - target: any model instance (order, invoice, payment, ...)
    - extra: optional dict with additional data (will be stored as JSON)
    """
    data: dict[str, Any] = {
        "action": action,
        "message": message or "",
        "extra": extra or {},
    }

    # Normalize actor
    if actor is not None and getattr(actor, "is_authenticated", False):
        data["actor"] = actor

    # Attach generic target
    if target is not None:
        ct = ContentType.objects.get_for_model(target.__class__)
        # try to use pk/id as string
        obj_id = getattr(target, "pk", None) or getattr(target, "id", None)
        if obj_id is not None:
            data["target_content_type"] = ct
            data["target_object_id"] = str(obj_id)

    return AuditLog.objects.create(**data)
