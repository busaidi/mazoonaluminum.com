# core/services/audit.py

from __future__ import annotations

from typing import Any, Mapping, Optional

from django.contrib.contenttypes.models import ContentType

from core.models import AuditLog


def log_event(
    *,
    action: str | AuditLog.Action,
    message: str = "",
    actor: Any = None,
    target: Optional[Any] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> AuditLog:
    """
    Create a single audit log entry.

    Parameters
    ----------
    action:
        The action code to store. Prefer using AuditLog.Action.* enums, e.g.:
        - AuditLog.Action.CREATE
        - AuditLog.Action.UPDATE
        - AuditLog.Action.DELETE
        - AuditLog.Action.STATUS_CHANGE
        - AuditLog.Action.NOTIFICATION
        - AuditLog.Action.OTHER

    message:
        Human-readable description of what happened (Arabic or English).

    actor:
        The user who performed the action, or None if not applicable.
        Only stored if user.is_authenticated is True.

    target:
        Optional model instance that this event relates to
        (SalesDocument, Invoice, Payment, etc.). It will be stored via
        GenericForeignKey (target_content_type + target_object_id).

    extra:
        Optional mapping of additional structured data (will be stored as JSON).

    Returns
    -------
    AuditLog
        The created AuditLog instance.
    """

    # -------- Normalize and validate action --------
    if isinstance(action, AuditLog.Action):
        action_value = action.value
    else:
        action_value = str(action)

    valid_actions = {choice[0] for choice in AuditLog.Action.choices}
    if action_value not in valid_actions:
        raise ValueError(
            f"Invalid audit action '{action_value}'. "
            f"Allowed values: {sorted(valid_actions)}"
        )

    data: dict[str, Any] = {
        "action": action_value,
        "message": message or "",
        # Copy extra to avoid mutating external dict
        "extra": dict(extra) if extra is not None else {},
    }

    # -------- Actor --------
    if actor is not None and getattr(actor, "is_authenticated", False):
        data["actor"] = actor

    # -------- Target object (via GenericForeignKey) --------
    if target is not None:
        # Use real model class (handles inheritance/proxy models correctly)
        ct = ContentType.objects.get_for_model(target, for_concrete_model=True)

        obj_id = getattr(target, "pk", None) or getattr(target, "id", None)
        if obj_id is not None:
            data["target_content_type"] = ct
            data["target_object_id"] = str(obj_id)

    # -------- Create the audit log entry --------
    return AuditLog.objects.create(**data)
